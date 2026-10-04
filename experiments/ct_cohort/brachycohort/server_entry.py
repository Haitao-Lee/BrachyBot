"""Experiment-only service entry; imports exactly the pinned product checkout."""
import os
import sys
from pathlib import Path


def main():
    checkout, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
    sys.path.insert(0, str(checkout))
    import web.server as server
    server._configure_file_logging()
    original_factory = server.create_app
    def isolated_factory(config=None):
        app = original_factory(config)
        # Preserve product startup/shutdown handlers; only the cookie is scoped.
        if app is not None:
            app.config["SESSION_COOKIE_NAME"] = os.environ["COHORT_COOKIE_NAME"]
        return app
    server.create_app = isolated_factory
    server.run_server(port=port, host="127.0.0.1", config={"session_id": "cohort", "agent_config": {}})


if __name__ == "__main__":
    main()
