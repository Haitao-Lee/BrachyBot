"""Exercise the real production entrypoint on loopback with an isolated runtime."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


@pytest.mark.skipif(importlib.util.find_spec("waitress") is None, reason="Install deploy/public/requirements.txt")
def test_real_public_origin(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRACHYBOT_")}
    env.update({"BRACHYBOT_PUBLIC_ORIGIN": "https://brachy.example.com",
                "BRACHYBOT_PUBLIC_PORT": str(port),
                "BRACHYBOT_API_KEY": "test-api-" + "a" * 48,
                "BRACHYBOT_SECRET_KEY": "test-cookie-" + "b" * 48,
                "BRACHYBOT_RUNTIME_DIR": str(tmp_path / "isolated-runtime")})
    root = Path(__file__).resolve().parents[1]

    def request(path, *, host="brachy.example.com", proto="https", data=None):
        headers = {"Host": host, "X-Forwarded-Proto": proto,
                   "X-Forwarded-For": "192.0.2.10", "X-API-Key": env["BRACHYBOT_API_KEY"]}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
                                     headers=headers, data=data)
        try:
            return urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc

    with (tmp_path / "server.log").open("w+") as logfile:
        proc = subprocess.Popen([sys.executable, "-m", "web.public_server"], cwd=root,
                                env=env, stdout=logfile, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while True:
                assert proc.poll() is None, "Isolated production server exited during startup"
                try:
                    with request("/") as response:
                        assert response.status == 200
                    break
                except (urllib.error.URLError, OSError):
                    if time.monotonic() >= deadline:
                        pytest.fail("Isolated production server did not become ready")
                    time.sleep(.25)
            with request("/api/auth/me") as response:
                assert response.code == 401
                assert "no-store" in response.headers["Cache-Control"]
            with request("/api/auth/register", data=b"{}") as response:
                assert response.code == 403
                assert json.load(response)["code"] == "registration_closed"
            with request("/", host="evil.example.com") as response:
                assert response.code == 400
            with request("/", proto="http") as response:
                assert response.code == 400
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
