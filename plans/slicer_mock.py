"""
Mock slicer module for BrachyBot
================================
Replaces 3D Slicer's slicer module with no-op stubs
so that core.py, utilizations.py etc. can run standalone.
"""


class _MockApp:
    """Mock slicer.app with no-op processEvents."""
    @staticmethod
    def processEvents():
        pass  # No UI to update in headless mode


class _MockModule:
    """Mock for slicer.modules.*"""
    pass


# The module-level objects that Zhiyuan code expects
app = _MockApp()
modules = _MockModule()
mrmlScene = None
util = None
