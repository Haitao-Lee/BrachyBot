# Validation Record — 2026-09-08

The deployment base code has been synced to `rtx3090_external:<workspace>/BrachyBot`.
Production units were not enabled, the existing 8080 service was not restarted, and no cases were migrated.

Passed:
- `tests/test_public_deployment.py tests/test_workspace_auth.py`: 32 passed, 3 third-party SWIG deprecation warnings.
- `tests/test_public_http.py`: 1 passed. Real Waitress + full create_app, temporary independent runtime.
- `tests/test_public_proxy.py`: 1 passed. Real Nginx + temporary self-signed certificate + loopback SSE test backend.
- systemd-analyze --user verify: both the public and tunnel units pass.
- ssh -G: the dedicated configuration parses successfully; does not connect to the remote.

The proxy tests confirmed: the first SSE can be read before the response ends; the deployment key is injected at the proxy;
client-forged X-Forwarded-For/Proto are overridden; API no-store and HSTS take effect.
The real application tests confirmed: unknown Host and HTTP requests are rejected, the anonymous API returns 401, and registration returns 403.
The account tests confirmed: an invited account can log in, secure cookies, CSRF, and the existing account/case isolation regression pass.

Test dependencies were only downloaded/extracted to `/tmp`: Waitress 3.0.2, Ubuntu Nginx 1.18 used for configuration compatibility verification;
not installed as a system service. A production VPS should install a supported and security-patched Nginx package.
The newer Nginx package link in the distribution cache returned 404, so the tests used an existing downloadable version;
this does not constitute a recommendation to use that old version for public production.

Still pending real-infrastructure validation: domain DNS, publicly trusted certificate and renewal, SSH host identity and tunnel reconnection,
public port isolation, actual 500 MiB file upload, long-running planning, browser end-to-end, multi-user GPU load,
backup recovery. None of these not-yet-executed checks are reported as complete.
