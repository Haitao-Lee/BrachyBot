#!/usr/bin/env python3
"""One live task through the actual browser conversation entry.

No direct BrachyAgent fallback based on provider credentials. Requires a trusted
isolated browser factory, fixture driver and private evaluator configuration;
without them exits BLOCKED (2), before any model call.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys

BB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BB))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=str(BB / "tasks/D1-SA-007.json"))
    parser.add_argument("--out", default="results/live")
    parser.add_argument("--evaluator-config")
    parser.add_argument("--collector")
    parser.add_argument("--response-checker")
    parser.add_argument("--completion-checker")
    args = parser.parse_args(argv)
    if not os.environ.get("BRACHYBENCH_BROWSER_SESSION_FACTORY") or not args.evaluator_config or not args.collector:
        print("BLOCKED: isolated browser session factory, private evaluator config and independent collector required; zero SUT calls")
        return 2
    from tools import run_task
    command = ["--task", args.task, "--out", args.out, "--adapter", "browser-user-chat",
               "--evaluator-config", args.evaluator_config, "--collector", args.collector]
    for name in ("response_checker", "completion_checker"):
        if getattr(args, name):
            command += ["--" + name.replace("_", "-"), getattr(args, name)]
    return run_task.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
