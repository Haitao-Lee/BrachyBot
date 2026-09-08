"""Optional real Nginx transport test (NGINX_TEST_BINARY), no public listener."""
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
import urllib.request

import pytest
from flask import Flask, Response, request
from werkzeug.serving import make_server


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(not os.environ.get("NGINX_TEST_BINARY"), reason="Set NGINX_TEST_BINARY for real proxy validation")
def test_nginx_template_tls_headers_and_unbuffered_sse(tmp_path):
    binary = os.environ["NGINX_TEST_BINARY"]
    app = Flask(__name__)
    release = threading.Event()

    @app.get("/api/events")
    def events():
        observed = {"key": request.headers.get("X-API-Key"),
                    "ip": request.headers.get("X-Forwarded-For"),
                    "proto": request.headers.get("X-Forwarded-Proto")}
        def stream():
            yield "data: " + json.dumps(observed) + "\n\n"
            release.wait(5)
            yield "data: done\n\n"
        return Response(stream(), mimetype="text/event-stream")

    backend = make_server("127.0.0.1", 0, app, threaded=True)
    worker = threading.Thread(target=backend.serve_forever, daemon=True)
    worker.start()
    port, http_port = free_port(), free_port()
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=brachy.example.com"], check=True, capture_output=True)
    secret = tmp_path / "proxy-key.conf"
    secret.write_text('proxy_set_header X-API-Key "internal-test-key";\n')
    text = (Path(__file__).resolve().parents[1] / "deploy/public/nginx.conf.example").read_text()
    text = text.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
    text = text.replace("listen 443 ssl;", f"listen 127.0.0.1:{port} ssl;")
    text = text.replace("/etc/letsencrypt/live/brachy.example.com/fullchain.pem", str(cert))
    text = text.replace("/etc/letsencrypt/live/brachy.example.com/privkey.pem", str(key))
    text = text.replace("/etc/nginx/brachybot-api-key.conf", str(secret))
    text = text.replace("/var/log/nginx/", str(tmp_path) + "/")
    text = text.replace("http://127.0.0.1:18082", f"http://127.0.0.1:{backend.server_port}")
    config = tmp_path / "nginx.conf"
    config.write_text(f"daemon off;\npid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
                      "events {}\nhttp {\naccess_log off;\n"
                      + "\n".join(f"{kind}_temp_path {tmp_path}/{kind};" for kind in
                                    ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
                      + "\n" + text + "\n}\n")
    command = [binary, "-p", str(tmp_path) + "/", "-c", str(config)]
    syntax = subprocess.run(command + ["-t"], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    with (tmp_path / "nginx.log").open("w") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 5
            while True:
                assert proc.poll() is None
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(.05)
            req = urllib.request.Request(f"https://127.0.0.1:{port}/api/events", headers={
                "Host": "brachy.example.com", "X-API-Key": "forged",
                "X-Forwarded-For": "203.0.113.99", "X-Forwarded-Proto": "http"})
            # Self-signed fixture certificate only; external check_public verifies TLS normally.
            context = ssl._create_unverified_context()
            start = time.monotonic()
            with urllib.request.urlopen(req, context=context, timeout=3) as response:
                first = response.readline().decode()
                assert time.monotonic() - start < 3
                assert json.loads(first.removeprefix("data: ")) == {
                    "key": "internal-test-key", "ip": "127.0.0.1", "proto": "https"}
                assert "no-store" in response.headers["Cache-Control"]
                assert response.headers["Strict-Transport-Security"]
                release.set()
                assert b"data: done" in response.read()
        finally:
            release.set()
            proc.terminate()
            proc.wait(timeout=5)
            backend.shutdown()
            backend.server_close()
