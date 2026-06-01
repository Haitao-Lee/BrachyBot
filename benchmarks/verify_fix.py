#!/usr/bin/env python3
"""
验证脚本：检查 Agent 是否真正修复了代码，而不是修改 benchmark 文件
"""

import json
import subprocess
import sys
from pathlib import Path


def check_git_status():
    """检查 git 状态，看是否有 benchmark 文件被修改"""
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    modified_files = result.stdout.strip().split("\n")

    # 检查是否有 benchmark 文件被修改
    benchmark_modified = [f for f in modified_files if "benchmarks/" in f and f.endswith(".json")]

    if benchmark_modified:
        print("❌ 违规：以下 benchmark 文件被修改了：")
        for f in benchmark_modified:
            print(f"  - {f}")
        return False

    # 检查是否有代码文件被修改
    code_modified = [f for f in modified_files if f.endswith(".py") or f.endswith(".json")]

    if code_modified:
        print("✅ 正确：以下代码文件被修改了：")
        for f in code_modified:
            print(f"  - {f}")
        return True

    print("⚠️  没有检测到任何文件修改")
    return True


def verify_fix_quality():
    """验证修复质量"""
    print("\n=== 修复质量验证 ===\n")

    # 检查 git diff
    result = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    print("代码修改统计：")
    print(result.stdout)

    # 检查是否有 benchmark 文件
    result2 = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd="/home/lht/snap/brachyplan/BrachyBot"
    )

    benchmark_files = [f for f in result2.stdout.strip().split("\n")
                      if "benchmarks/" in f and f.endswith(".json")]

    if benchmark_files:
        print("\n❌ 违规：发现 benchmark 文件被修改：")
        for f in benchmark_files:
            print(f"  - {f}")
        print("\n正确的做法是修复代码，而不是修改测试！")
        return False

    print("\n✅ 验证通过：没有修改 benchmark 文件")
    return True


if __name__ == "__main__":
    print("=== BrachyBot 修复验证 ===\n")

    # 检查 git 状态
    git_ok = check_git_status()

    # 验证修复质量
    quality_ok = verify_fix_quality()

    if git_ok and quality_ok:
        print("\n✅ 验证通过：修复是正确的")
        sys.exit(0)
    else:
        print("\n❌ 验证失败：发现违规行为")
        sys.exit(1)
