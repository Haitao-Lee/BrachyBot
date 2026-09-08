"""Read-only external smoke checks. Does not log in, register, or upload data."""
import argparse
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="https://your-domain (no trailing slash)")
    args = parser.parse_args()
    parsed = urlsplit(args.origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        parser.error("Supply only an HTTPS origin")
    opener = urllib.request.build_opener(NoRedirect())
    failed = False
    for path, expected in (("/", 200), ("/api/auth/me", 401), ("/api/status?lightweight=1", 401)):
        try:
            response = opener.open(args.origin + path, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, urllib.error.URLError) as exc:
            print(f"FAIL {path}: transport failure ({type(exc).__name__})")
            failed = True
            continue
        with response:
            ok = response.code == expected and bool(response.headers.get("Strict-Transport-Security"))
            if path.startswith("/api/"):
                ok = ok and "no-store" in response.headers.get("Cache-Control", "")
            print(f"{'PASS' if ok else 'FAIL'} {path}: HTTP {response.code}")
            failed |= not ok
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
