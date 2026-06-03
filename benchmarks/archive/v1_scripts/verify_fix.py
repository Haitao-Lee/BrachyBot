#!/usr/bin/env python3
"""
Verification script: Check if Agent truly fixed code instead of modifying benchmark files.
"""

import json
import subprocess
import sys
from pathlib import Path


def check_git_status():
    """Check git status to see if any benchmark files were modified"""
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    modified_files = result.stdout.strip().split("\n") if result.stdout.strip() else []

    # Check if any benchmark files were modified
    benchmark_modified = [f for f in modified_files if "benchmarks/" in f and f.endswith(".json")]

    if benchmark_modified:
        print("❌ VIOLATION: The following benchmark files were modified:")
        for f in benchmark_modified:
            print(f"  - {f}")
        return False

    # Check if any code files were modified
    code_modified = [f for f in modified_files if f.endswith(".py") or f.endswith(".json")]

    if code_modified:
        print("✅ CORRECT: The following code files were modified:")
        for f in code_modified:
            print(f"  - {f}")
        return True

    print("⚠️  No file modifications detected")
    return True


def verify_fix_quality():
    """Verify fix quality"""
    print("\n=== Fix Quality Verification ===\n")

    # Check git diff
    result = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    print("Code modification statistics:")
    print(result.stdout)

    # Check if any benchmark files were modified
    result2 = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    benchmark_files = [f for f in result2.stdout.strip().split("\n")
                      if "benchmarks/" in f and f.endswith(".json")]

    if benchmark_files:
        print("\n❌ VIOLATION: Benchmark files were modified:")
        for f in benchmark_files:
            print(f"  - {f}")
        print("\nCorrect approach: Fix code, not tests!")
        return False

    print("\n✅ Verification passed: No benchmark files were modified")
    return True


if __name__ == "__main__":
    print("=== BrachyBot Fix Verification ===\n")

    # Check git status
    git_ok = check_git_status()

    # Verify fix quality
    quality_ok = verify_fix_quality()

    if git_ok and quality_ok:
        print("\n✅ Verification passed: Fix is correct")
        sys.exit(0)
    else:
        print("\n❌ Verification failed: Violations detected")
        sys.exit(1)
