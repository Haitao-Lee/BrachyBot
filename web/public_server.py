"""Opt-in production entrypoint: one process owns all live case workers.

Run from the repository root: python -m web.public_server --check
The environment must be supplied BEFORE importing web.server/server_support.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def validate_environment(env):
    origin = env.get("BRACHYBOT_PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("BRACHYBOT_PUBLIC_ORIGIN must be an HTTPS origin without a trailing slash")
    if parsed.port not in (None, 443):
        raise ValueError("The public entrypoint must use HTTPS port 443")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname) or "change_me" in origin.lower():
        raise ValueError("Replace the public hostname placeholder with a valid DNS hostname")
    for key in ("BRACHYBOT_API_KEY", "BRACHYBOT_SECRET_KEY"):
        value = env.get(key, "")
        if len(value) < 32 or "CHANGE_ME" in value or "<" in value:
            raise ValueError(f"{key} must contain an independently generated secret (at least 32 characters)")
    if env["BRACHYBOT_API_KEY"] == env["BRACHYBOT_SECRET_KEY"]:
        raise ValueError("The API key and cookie signing secret must be different")
    runtime = env.get("BRACHYBOT_RUNTIME_DIR", "")
    if not runtime or not Path(runtime).is_absolute() or runtime == "/":
        raise ValueError("BRACHYBOT_RUNTIME_DIR must explicitly identify an absolute runtime directory")
    for key, value in env.items():
        if ((key.startswith("BRACHYBOT_ENABLE_") or key in {
                "BRACHYBOT_TRUST_NETWORK", "BRACHYBOT_ALLOW_INSECURE_REMOTE",
                "BRACHYBOT_TRUST_PROXY", "BRACHYBOT_ALLOW_SELF_REGISTRATION"})
                and str(value).lower() in {"1", "true", "yes", "on"}):
            raise ValueError(f"Disable {key} in the public service environment")
    port = int(env.get("BRACHYBOT_PUBLIC_PORT", "18082"))
    threads = int(env.get("BRACHYBOT_PUBLIC_THREADS", "16"))
    if not 1024 <= port <= 65535 or not 4 <= threads <= 64:
        raise ValueError("Use an unprivileged port and 4-64 application threads")
    return parsed.netloc, port, threads


def configure_public_app(app, public_host):
    from flask import jsonify, request

    @app.before_request
    def public_boundary():
        if request.host.lower() != public_host.lower():
            return jsonify(error="Unknown host"), 400
        if not request.is_secure:
            return jsonify(error="HTTPS required"), 400

    # Apply the transport check before authentication, including auth endpoints.
    hooks = app.before_request_funcs[None]
    hooks.insert(0, hooks.pop())

    @app.after_request
    def public_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without opening a port or workspace")
    args = parser.parse_args()
    try:
        host, port, threads = validate_environment(os.environ)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.check:
        print("Production configuration valid; listener will be loopback-only. No workspace opened.")
        return
    # Fixed here so inherited development settings cannot weaken this entrypoint.
    os.environ.update({
        "BRACHYBOT_DEPLOYMENT_MODE": "public",
        "BRACHYBOT_DEBUG_ACCOUNT_ENABLED": "0",
        "BRACHYBOT_DEBUG_ACCOUNT": "",
        "BRACHYBOT_COOKIE_SECURE": "1", "BRACHYBOT_REQUIRE_API_KEY": "1",
        "BRACHYBOT_ALLOW_SELF_REGISTRATION": "0", "BRACHYBOT_TRUST_PROXY": "0",
        "ALLOWED_ORIGINS": os.environ["BRACHYBOT_PUBLIC_ORIGIN"],
    })
    # Waitress owns proxy parsing; the app must not reparse an untrusted XFF.
    from waitress import serve
    from web.server import create_app
    # Prevent two public processes from hydrating and mutating one workspace.
    import fcntl
    runtime = Path(os.environ["BRACHYBOT_RUNTIME_DIR"])
    runtime.mkdir(parents=True, exist_ok=True)
    lock = (runtime / ".public-server.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("Another public server or account administrator owns this runtime")
    app = create_app()
    configure_public_app(app, host)
    serve(app, host="127.0.0.1", port=port, threads=threads,
          # Memory-mapped case arrays legitimately hold ~1000 descriptors; the
          # default select(2) loop dies above FD_SETSIZE (1023).
          asyncore_use_poll=True,
          trusted_proxy="127.0.0.1", trusted_proxy_count=1,
          trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
          clear_untrusted_proxy_headers=True, channel_timeout=3600,
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"],
          expose_tracebacks=False, ident="BrachyBot")


if __name__ == "__main__":
    main()
