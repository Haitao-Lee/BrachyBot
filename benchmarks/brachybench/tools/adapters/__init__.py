"""SUT adapters for BrachyBench (DESIGN §26.1).

An adapter only **translates** a SUT's observable behaviour into the uniform
``observation`` dict consumed by ``tools/run_task.py``.  It must never score.
"""
