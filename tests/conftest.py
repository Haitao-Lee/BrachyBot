"""
Pytest Configuration
===================
"""

import os
import sys
import importlib
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# The deployment parent directory can contain an unrelated ``config.py``.
# Pytest may import it before application modules, shadowing this project's
# ``config`` package and making test collection depend on the caller's cwd.
# Keep the correction test-only; production startup already anchors its path.
_loaded_config = sys.modules.get("config")
if _loaded_config is not None and not hasattr(_loaded_config, "__path__"):
    _config_file = os.path.realpath(str(getattr(_loaded_config, "__file__", "")))
    _project_config = os.path.realpath(os.path.join(PROJECT_ROOT, "config"))
    if not _config_file.startswith(_project_config + os.sep):
        del sys.modules["config"]

# Import the intended package now.  This prevents a later pytest plugin or
# parent-directory helper from inserting a same-named flat module into
# ``sys.modules`` before application imports begin.
importlib.import_module("config")


@pytest.fixture(autouse=True)
def isolated_auth_fixture(monkeypatch):
    """Existing account tests explicitly opt into enrollment; not a server default.

    Clear process-wide auth budgets between tests, never between real requests.
    Default-closed tests delete this environment override in their own scope.
    """
    monkeypatch.setenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", "1")
    from web import server_support
    with server_support._rate_limit_lock:
        server_support._rate_limit_auth_store.clear()
