"""Deterministic monitor presentation and checkpoint selection (single implementation)."""
from typing import Any, Dict, Optional
import re


def _monitor_step_zh(label: str) -> str:
    labels = {
        "CTV segmentation": "CTV 分割", "OAR segmentation": "OAR 分割",
        "Trajectory initialization": "轨迹初始化", "Trajectory refinement": "轨迹优化",
        "Seed planning": "粒子布源", "Dose calculation": "剂量计算",
        "Dose evaluation": "剂量评估", "Full planning pipeline": "完整规划流程",
    }
    return labels.get(label, label)


def _monitor_step_label(key: str, language: str = "en") -> str:
    labels = {
        "ctv": ("CTV \u5206\u5272", "CTV segmentation"),
        "oar": ("OAR \u5206\u5272", "OAR segmentation"),
        "trajectory_init": ("\u8f68\u8ff9\u521d\u59cb\u5316", "Trajectory initialization"),
        "trajectory_refine": ("\u8f68\u8ff9\u4f18\u5316", "Trajectory refinement"),
        "seed_planning": ("\u7c92\u5b50\u5e03\u6e90", "Seed planning"),
        "dose_calc": ("\u5242\u91cf\u8ba1\u7b97", "Dose calculation"),
        "dose_eval": ("\u5242\u91cf\u8bc4\u4f30", "Dose evaluation"),
        "full": ("\u5b8c\u6574\u89c4\u5212\u6d41\u7a0b", "Full planning pipeline"),
    }
    pair = labels.get(key, (key or "\u6b65\u9aa4", key or "step"))
    return pair[0] if language == "zh" else pair[1]


def _localize_monitor_text(value: Any, language: str = "en") -> str:
    raw = str(value or "")
    if language != "zh" or not raw:
        return raw
    exact = {
        "Operation failed; inspect the error details and confirm the input data.": "操作失败，请查看错误详情并确认输入数据。",
        "Seed edit recorded. Recompute dose and verify DVH before placing the next seed.": "已记录粒子编辑。请重新计算剂量并核对 DVH，再放置下一枚粒子。",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.": "剂量预览已更新。请打开分析面板查看 DVH 和 OAR 剂量。",
        "If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.": "若该部位的热点不符合临床要求，可沿针道分散中央粒子或降低局部粒子密度。",
        "Case resources are still loading; detailed planning metrics will be available when hydration completes.": "病例资源仍在加载，完成后可查看详细规划指标。",
        "The Surgical Guide is persisted or being restored; wait for case resources to finish loading before judging whether it exists.": "导板已持久化或正在恢复，请等待病例资源加载完成后再判断其状态。",
        "The Surgical Guide status is temporarily unavailable because case resources could not be fully restored.": "病例资源尚未完整恢复，暂时无法获取导板状态。",
        "The Surgical Guide generation failed; inspect the recorded error before retrying.": "导板生成失败，请查看已记录的错误后重试。",
        "Load CT, segment CTV/OAR, and run planning or manual AI dose recomputation to generate actionable advice.": "请加载 CT、分割 CTV/OAR，并完成规划或手动剂量重算，以生成具体建议。",
        "Run dose evaluation to make V100/D90 advice available.":
            "\u8bf7\u5148\u6267\u884c\u5242\u91cf\u8bc4\u4f30\uff0c\u4ee5\u4fbf\u751f\u6210 V100/D90 \u5efa\u8bae\u3002",
        "Inspect cold CTV regions against the intended prescription coverage, then recompute dose and DVH after edits.":
            "\u8bf7\u68c0\u67e5 CTV \u7684\u4f4e\u5242\u91cf\u533a\u57df\uff0c\u7f16\u8f91\u540e\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u548c DVH\u3002",
        "Compare D90 with the source-backed prescription convention for this tumor site before labeling coverage adequate or inadequate.":
            "\u5224\u65ad\u8986\u76d6\u662f\u5426\u5145\u5206\u524d\uff0c\u8bf7\u5c06 D90 \u4e0e\u8be5\u90e8\u4f4d\u6709\u6765\u6e90\u4f9d\u636e\u7684\u5904\u65b9\u89c4\u8303\u8fdb\u884c\u6bd4\u8f83\u3002",
        "Compare OAR doses against applicable site-specific guidance or the confirmed case protocol before classifying safety.":
            "\u5224\u65ad\u5b89\u5168\u6027\u524d\uff0c\u8bf7\u4f9d\u636e\u9002\u7528\u7684\u90e8\u4f4d\u7279\u5f02\u6027\u6307\u5357\u6216\u5df2\u786e\u8ba4\u7684\u75c5\u4f8b\u65b9\u6848\u6bd4\u8f83 OAR \u5242\u91cf\u3002",
        "Review whether the current seed count and spacing are sufficient for the requested coverage after applying source-backed criteria.":
            "\u6839\u636e\u6709\u6765\u6e90\u7684\u6807\u51c6\uff0c\u68c0\u67e5\u5f53\u524d\u7c92\u5b50\u6570\u91cf\u548c\u95f4\u8ddd\u662f\u5426\u8db3\u4ee5\u8fbe\u5230\u76ee\u6807\u8986\u76d6\u3002",
        "Recent manual edits were detected; recompute dose after each seed or needle adjustment to keep DVH current.":
            "\u68c0\u6d4b\u5230\u8fd1\u671f\u624b\u52a8\u7f16\u8f91\uff1b\u6bcf\u6b21\u8c03\u6574\u7c92\u5b50\u6216\u9488\u9053\u540e\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\uff0c\u4ee5\u4fdd\u6301 DVH \u4e3a\u6700\u65b0\u7ed3\u679c\u3002",
        "No seeds are present. Add a needle and place seeds through the CTV before dose evaluation.":
            "\u5f53\u524d\u6ca1\u6709\u7c92\u5b50\u3002\u8bf7\u5148\u6dfb\u52a0\u9488\u9053\u5e76\u5728 CTV \u5185\u5e03\u7f6e\u7c92\u5b50\uff0c\u518d\u8fdb\u884c\u5242\u91cf\u8bc4\u4f30\u3002",
        "Dose preview updated. Open Analysis to inspect DVH and OAR dose.":
            "\u5242\u91cf\u9884\u89c8\u5df2\u66f4\u65b0\u3002\u8bf7\u6253\u5f00\u5206\u6790\u9762\u677f\u67e5\u770b DVH \u548c OAR \u5242\u91cf\u3002",
        "Seed geometry was not available for the monitor; verify seed spacing directly in the 3D viewer.":
            "\u76d1\u6d4b\u5668\u672a\u83b7\u53d6\u7c92\u5b50\u51e0\u4f55\u4fe1\u606f\uff0c\u8bf7\u76f4\u63a5\u5728 3D \u67e5\u770b\u5668\u4e2d\u6838\u5bf9\u7c92\u5b50\u95f4\u8ddd\u3002",
        "Inspect the highlighted seed pairs in the 3D viewer, correct their axial spacing, and recompute dose before final review.":
            "\u8bf7\u5728 3D viewer \u4e2d\u68c0\u67e5\u9ad8\u4eae\u7c92\u5b50\u7ec4\u5408\uff0c\u4fee\u6b63\u8f74\u5411\u95f4\u8ddd\u5e76\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u3002",
        "Move or remove every obstacle-intersecting needle before dose review or Surgical Guide generation.":
            "\u8bf7\u5728\u5242\u91cf\u5ba1\u6838\u6216\u751f\u6210\u624b\u672f\u5bfc\u677f\u524d\uff0c\u79fb\u52a8\u6216\u5220\u9664\u6240\u6709\u4e0e\u4e0d\u53ef\u7a7f\u523a\u7ed3\u6784\u76f8\u4ea4\u7684\u9488\u9053\u3002",
        "Review the highlighted needle pairs for physical collision and guide-sleeve manufacturability.":
            "\u8bf7\u68c0\u67e5\u9ad8\u4eae\u9488\u9053\u7ec4\u5408\u662f\u5426\u53d1\u751f\u7269\u7406\u78b0\u649e\uff0c\u5e76\u786e\u8ba4\u5bfc\u5411\u5957\u7b52\u53ef\u5236\u9020\u3002",
        "Recompute the outdated dose/DVH and regenerate the Surgical Guide before finalizing the plan.":
            "\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5df2\u8fc7\u671f\u7684\u5242\u91cf\u548c DVH\uff0c\u5e76\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u540e\u518d\u5b8c\u6210\u89c4\u5212\u3002",
        "No Surgical Guide has been generated for the current needle plan.":
            "\u5f53\u524d\u9488\u9053\u89c4\u5212\u5c1a\u672a\u751f\u6210\u624b\u672f\u5bfc\u677f\u3002",
        "The Surgical Guide does not match the current planning version.":
            "\u624b\u672f\u5bfc\u677f\u4e0e\u5f53\u524d\u9488\u9053\u89c4\u5212\u4e0d\u4e00\u81f4\uff0c\u5df2\u6807\u8bb0\u4e3a\u8fc7\u671f\u3002",
    }
    if raw in exact:
        return exact[raw]
    patterns = (
        (r"Seed edit recorded\. Current V100 is ([0-9.]+)%; inspect cold CTV regions after recompute\.",
         lambda m: f"已记录粒子编辑。当前 V100 为 {m[1]}%；重算后请检查 CTV 低剂量区域。"),
        (r"Seed edit recorded\. ([0-9]+) pair\(s\) violate the physical spacing rule; the worst pair is (.+) and (.+) with ([0-9.]+) mm surface clearance\. A focused 3D checkpoint is ready; correct the spacing before continuing\.",
         lambda m: f"已记录粒子编辑。{m[1]} 组粒子违反物理间距要求；最严重的一组是 {m[2]} 与 {m[3]}，表面间隙为 {m[4]} mm。已准备对应的 3D 特写，请先调整间距再继续。"),
        (r"Needle edit recorded\. (.+) intersect the current Data Tree non-traversable structures; correct these paths before continuing\.",
         lambda m: f"针道编辑已记录。针道 {m[1]} 与当前 Data Tree 中的不可穿刺结构相交，请先修正路径。"),
        (r"Needle edit recorded\. (.+) and (.+) are ([0-9.]+) mm apart, below the ([0-9.]+) mm minimum\.",
         lambda m: f"针道编辑已记录。{m[1]} 与 {m[2]} 的最短距离为 {m[3]} mm，低于要求的 {m[4]} mm。"),
        (r"(.+) is running; I will verify the Data Tree and viewer output when it finishes\.",
         lambda m: f"{_monitor_step_zh(m[1])} 正在执行；完成后我会核对 Data Tree 和 viewer 输出。"),
        (r"(.+) completed; verify the Data Tree and viewer output before the next prerequisite step\.",
         lambda m: f"{_monitor_step_zh(m[1])} 已完成；请先核对 Data Tree 和 viewer 输出，再继续下一步。"),
        (r"(.+) failed; inspect the error details and confirm the input data\.",
         lambda m: f"{_monitor_step_zh(m[1])} 执行失败；请检查错误详情并确认输入数据。"),
        (r"(.+) event recorded; verify its Data Tree output\.",
         lambda m: f"已记录{_monitor_step_zh(m[1])}事件；请核对 Data Tree 输出。"),
        (r"([0-9]+) seed pair\(s\) violate the physical spacing rule \(seed ([0-9.]+) mm x ([0-9.]+) mm; minimum surface clearance ([0-9.]+) mm\)\. ([0-9]+) pair\(s\) geometrically overlap\.",
         lambda m: f"{m[1]} 组粒子违反物理间距要求（粒子 {m[2]} mm × {m[3]} mm，最小表面间隙 {m[4]} mm），其中 {m[5]} 组发生几何重叠。"),
        (r"Dose preview updated: V100=([0-9.]+)%, D90=([0-9.]+) Gy\. Review hot spots and OAR dose before adding seeds\.",
         lambda m: f"剂量预览已更新：V100={m[1]}%，D90={m[2]} Gy。添加粒子前请检查热点和 OAR 剂量。"),
        (r"CTV V100 is ([0-9.]+)%; compare it with the applicable site-specific guidance or confirmed case protocol target\.",
         lambda match: f"CTV V100 \u4e3a {match.group(1)}%\uff0c\u8bf7\u4e0e\u9002\u7528\u7684\u90e8\u4f4d\u7279\u5f02\u6027\u6307\u5357\u6216\u5df2\u786e\u8ba4\u7684\u75c5\u4f8b\u65b9\u6848\u76ee\u6807\u6bd4\u8f83\u3002"),
        (r"CTV D90 is ([0-9.]+) Gy(?:; current dose reference is ([0-9.]+) Gy)?\.",
         lambda match: f"CTV D90 \u4e3a {match.group(1)} Gy" + (f"\uff0c\u5f53\u524d\u5242\u91cf\u53c2\u8003\u4e3a {match.group(2)} Gy" if match.group(2) else "") + "\u3002"),
        (r"CTV V200 is ([0-9.]+)%; inspect the corresponding hot-spot location in 2D/3D\.",
         lambda match: f"CTV V200 \u4e3a {match.group(1)}%\uff0c\u8bf7\u5728 2D/3D \u67e5\u770b\u5668\u4e2d\u68c0\u67e5\u5bf9\u5e94\u7684\u70ed\u70b9\u4f4d\u7f6e\u3002"),
        (r"CTV V150 is ([0-9.]+)%; interpret uniformity with the current site-specific criteria\.",
         lambda match: f"CTV V150 \u4e3a {match.group(1)}%\uff0c\u8bf7\u6309\u5f53\u524d\u90e8\u4f4d\u7279\u5f02\u6027\u6807\u51c6\u5224\u65ad\u5747\u5300\u6027\u3002"),
        (r"Plan score is ([0-9.]+)/100; use it as an advisory ranking signal, not approval\.",
         lambda match: f"\u89c4\u5212\u8bc4\u5206\u4e3a {match.group(1)}/100\uff0c\u8be5\u5206\u6570\u4ec5\u7528\u4e8e\u8f85\u52a9\u6392\u5e8f\uff0c\u4e0d\u4ee3\u8868\u4e34\u5e8a\u6279\u51c6\u3002"),
        (r"No seed pair violates the ([0-9.]+) mm minimum physical surface-clearance rule in the current committed plan\.",
         lambda match: f"\u5f53\u524d\u5df2\u63d0\u4ea4\u89c4\u5212\u4e2d\u6ca1\u6709\u7c92\u5b50\u5bf9\u8fdd\u53cd {match.group(1)} mm \u7684\u6700\u5c0f\u7269\u7406\u8868\u9762\u95f4\u9699\u8981\u6c42\u3002"),
        (r"(.+) \((.*)\) and (.+) \((.*)\): center distance ([0-9.]+) mm, surface clearance ([0-9.-]+) mm \[(.+)\]\.",
         lambda match: (
             f"\u7c92\u5b50 {match.group(1)}\uff08{match.group(2)}\uff09\u4e0e "
             f"{match.group(3)}\uff08{match.group(4)}\uff09\u7684\u4e2d\u5fc3\u8ddd\u79bb\u4e3a "
             f"{match.group(5)} mm\uff0c\u8868\u9762\u95f4\u9699\u4e3a {match.group(6)} mm"
             f"\uff08{match.group(7)}\uff09\u3002"
         )),
        (r"(.+) and (.+) are ([0-9.]+) mm apart \(minimum ([0-9.]+) mm; (.+)\)\.",
         lambda match: (
             f"\u9488\u9053 {match.group(1)} \u4e0e {match.group(2)} \u7684\u6700\u77ed\u8ddd\u79bb\u4e3a "
             f"{match.group(3)} mm\uff1b\u5f53\u524d\u914d\u7f6e\u7684\u6700\u5c0f\u8ddd\u79bb\u4e3a "
             f"{match.group(4)} mm\u3002"
         )),
    )
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, raw)
        if match:
            return formatter(match)
    if raw.startswith("Top OAR doses: "):
        return "OAR \u6700\u9ad8\u5242\u91cf\u7ed3\u6784\uff1a" + raw[len("Top OAR doses: "):]
    if raw.startswith("Needles intersecting current Data Tree non-traversable structures: "):
        names = raw[len("Needles intersecting current Data Tree non-traversable structures: "):].rstrip(".")
        return f"\u9488\u9053 {names} \u4e0e\u5f53\u524d Data Tree \u4e2d\u7684\u4e0d\u53ef\u7a7f\u523a\u7ed3\u6784\u76f8\u4ea4\u3002"
    if raw.startswith("Outdated dependent results: "):
        names = raw[len("Outdated dependent results: "):].rstrip(".")
        return f"\u624b\u52a8\u51e0\u4f55\u7f16\u8f91\u540e\uff0c\u89c4\u5212\u4ea7\u7269 {names} \u5df2\u8fc7\u671f\u3002"
    if raw.startswith("Needle edit recorded."):
        return "\u5df2\u8bb0\u5f55\u9488\u9053\u7f16\u8f91\u3002\u8bf7\u786e\u8ba4\u9488\u9053\u7ecf\u8fc7\u5b89\u5168\u7ec4\u7ec7\uff0c\u5e76\u4e0e\u4e0d\u53ef\u7a7f\u523a OAR \u4fdd\u6301\u8ddd\u79bb\u3002"
    if raw.startswith("Seed edit recorded."):
        return "\u5df2\u8bb0\u5f55\u7c92\u5b50\u7f16\u8f91\u3002\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf\u5e76\u6838\u5bf9 DVH\uff0c\u518d\u653e\u7f6e\u4e0b\u4e00\u679a\u7c92\u5b50\u3002"
    return raw


def _monitor_activity_label(key: str, language: str = "en") -> str:
    labels = {
        "planning.step": ("\u89c4\u5212\u6b65\u9aa4", "Planning steps"),
        "planning.error": ("规划失败", "Planning failures"),
        "segmentation.error": ("分割失败", "Segmentation failures"),
        "manual.needle.restore": ("恢复针道", "Needle restores"),
        "segmentation.step": ("\u5206\u5272\u6b65\u9aa4", "Segmentation steps"),
        "manual.needle.drag": ("\u624b\u52a8\u9488\u9053\u62d6\u62fd", "Manual needle drags"),
        "manual.needle.position_only": ("\u624b\u52a8\u9488\u9053\u4f4d\u7f6e\u8c03\u6574", "Manual needle position updates"),
        "manual.needle.add": ("\u624b\u52a8\u6dfb\u52a0\u9488\u9053", "Manual needle additions"),
        "manual.needle.delete": ("\u624b\u52a8\u5220\u9664\u9488\u9053", "Manual needle deletions"),
        "manual.seed.drag": ("\u624b\u52a8\u7c92\u5b50\u62d6\u62fd", "Manual seed drags"),
        "manual.seed.add": ("\u624b\u52a8\u6dfb\u52a0\u7c92\u5b50", "Manual seed additions"),
        "manual.seed.delete": ("\u624b\u52a8\u5220\u9664\u7c92\u5b50", "Manual seed deletions"),
        "manual.dose": ("\u624b\u52a8\u5242\u91cf\u91cd\u7b97", "Manual dose updates"),
        "ui.panel": ("\u9762\u677f\u64cd\u4f5c", "Panel interactions"),
        "ui.click": ("\u70b9\u51fb\u64cd\u4f5c", "Click interactions"),
        "ui.change": ("\u63a7\u4ef6\u4fee\u6539", "Control changes"),
        "ui.slider": ("\u6ed1\u5757\u8c03\u6574", "Slider changes"),
        "training.start": ("\u76d1\u6d4b\u542f\u52a8", "Monitor starts"),
        "training.stop": ("\u76d1\u6d4b\u7ed3\u675f", "Monitor stops"),
    }
    pair = labels.get(key)
    if pair:
        return pair[0] if language == "zh" else pair[1]
    return (key.replace(".", " ").strip().title() or "\u5176\u4ed6\u4e8b\u4ef6") if language == "zh" else (key.replace(".", " ").strip().title() or "Other events")


def _format_training_summary(events: list, counts: Dict[str, int], advice: Dict[str, Any], language: str = "en") -> str:
    total = sum(counts.values()) if counts else len(events)
    if language == "zh":
        lines = ["## \u89c4\u5212\u76d1\u6d4b\u603b\u7ed3", f"\u672c\u6b21\u76d1\u6d4b\u8bb0\u5f55\u4e86 {len(events)} \u4e2a\u754c\u9762\u6216\u89c4\u5212\u4e8b\u4ef6\u3002"]
        headings = ("\u6d3b\u52a8\u6982\u89c8", "\u5f53\u524d\u4f18\u52bf", "\u9700\u8981\u5173\u6ce8", "\u5efa\u8bae")
    else:
        lines = ["## Planning monitoring summary", f"Recorded {len(events)} UI/planning events."]
        headings = ("Activity", "Strengths", "Issues", "Recommendations")
    high_value_counts = {
        key: count for key, count in (counts or {}).items()
        if key not in {"ui.click", "ui.panel", "ui.change", "ui.slider"}
    }
    display_counts = high_value_counts or (counts or {})
    if display_counts:
        lines.extend(["", f"### {headings[0]}"])
        for key, count in sorted(display_counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {_monitor_activity_label(key, language)}: {count}")
    advice = advice or {}
    for heading, key in zip(headings[1:], ("strengths", "issues", "advice")):
        values = advice.get(key) or []
        if values:
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {_localize_monitor_text(value, language)}" for value in values)
    lines[1] = f"本次监测记录了 {total} 个界面或规划事件。" if language == "zh" else f"Recorded {total} UI/planning events."
    if total > len(events):
        lines.append(f"仅保留最近 {len(events)} 条事件明细，活动计数包含完整运行。" if language == "zh" else f"Only the latest {len(events)} event details are retained; counts cover the full run.")
    return "\n".join(lines)


def _training_feedback_for_event_source(agent, session_id: Optional[str], event: Dict[str, Any], *, snapshot=None) -> Optional[str]:
    from web import server_support as support
    event_type = str(event.get("type", ""))
    detail = support._monitor_event_detail(event)
    if event_type.startswith("manual.") and detail.get("commit_status") != "committed":
        # Manual previews can be rejected and rolled back. Monitor only the
        # server-owned commit event so its advice, screenshot and final counts
        # can never describe geometry that was not saved.
        return None
    language = support._monitor_language(event.get("language") or detail.get("language"))
    if event_type in {"planning.error", "segmentation.error"}:
        return "操作失败，请查看错误详情并确认输入数据。" if language == "zh" else "Operation failed; inspect the error details and confirm the input data."
    if not event_type.startswith("manual.") and event_type not in {"planning.step", "segmentation.step"}:
        return None
    snapshot = snapshot if snapshot is not None else support._latest_plan_snapshot(agent, validate_obstacles=False)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = support._volume_metric_as_fraction(metrics, "v100")
    d90 = support._extract_metric_value(metrics, "d90")
    target = support._source_backed_target_context(agent).get("criteria", {})
    v100_min = support._metric_as_fraction(support._extract_metric_value(target, "v100_min"))
    if event_type.startswith("manual.seed"):
        interference = snapshot.get("seed_interference") or {}
        if interference.get("status") == "attention":
            pairs = list(interference.get("close_pairs") or [])
            worst = min(
                pairs,
                key=lambda pair: float(pair.get("surface_clearance_mm") or 0.0),
            )
            if language == "zh":
                return (
                    f"已记录粒子编辑。检测到 {len(pairs)} 组粒子违反物理间距要求；"
                    f"最严重的是 {worst.get('first_id')} 与 {worst.get('second_id')}，"
                    f"表面间隙为 {float(worst.get('surface_clearance_mm') or 0.0):.2f} mm。"
                    "已准备对应的 3D 特写，请先调整间距再继续。"
                )
            return (
                f"Seed edit recorded. {len(pairs)} pair(s) violate the physical spacing rule; "
                f"the worst pair is {worst.get('first_id')} and {worst.get('second_id')} "
                f"with {float(worst.get('surface_clearance_mm') or 0.0):.2f} mm surface clearance. "
                "A focused 3D checkpoint is ready; correct the spacing before continuing."
            )
        if v100 is not None and v100_min is not None and v100 < v100_min:
            return _localize_monitor_text(
                f"Seed edit recorded. Current V100 is {v100 * 100:.1f}%; inspect cold CTV regions after recompute.",
                language,
            )
        return _localize_monitor_text("Seed edit recorded. Recompute dose and verify DVH before placing the next seed.", language)
    if event_type.startswith("manual.needle"):
        needle_geometry = snapshot.get("needle_geometry") or {}
        obstacle_hits = list(needle_geometry.get("obstacle_hits") or [])
        if obstacle_hits:
            names = ", ".join(obstacle_hits[:12])
            if language == "zh":
                return f"针道编辑已记录。针道 {names} 与当前 Data Tree 中的不可穿刺结构相交，请先修正路径。"
            return (
                f"Needle edit recorded. {names} intersect the current Data Tree "
                "non-traversable structures; correct these paths before continuing."
            )
        close_pairs = list(needle_geometry.get("close_pairs") or [])
        if close_pairs:
            worst = min(close_pairs, key=lambda pair: float(pair.get("distance_mm") or 0.0))
            if language == "zh":
                return (
                    f"针道编辑已记录。{worst.get('first_id')} 与 {worst.get('second_id')} "
                    f"的最短距离为 {float(worst.get('distance_mm') or 0.0):.2f} mm，"
                    f"低于要求的 {float(worst.get('minimum_distance_mm') or 0.0):.2f} mm。"
                )
            return (
                f"Needle edit recorded. {worst.get('first_id')} and {worst.get('second_id')} "
                f"are {float(worst.get('distance_mm') or 0.0):.2f} mm apart, below the "
                f"{float(worst.get('minimum_distance_mm') or 0.0):.2f} mm minimum."
            )
        return _localize_monitor_text(
            "Needle edit recorded. Check that the path traverses safe tissue and keeps distance from non-traversable OARs.",
            language,
        )
    if event_type in {"planning.step", "segmentation.step"}:
        stage = _monitor_step_label(support._monitor_step_key(event), language)
        status = support._monitor_event_status(event)
        if status == "running":
            return f"{stage} \u6b63\u5728\u6267\u884c\uff1b\u5b8c\u6210\u540e\u6211\u4f1a\u6838\u5bf9 Data Tree \u548c viewer \u8f93\u51fa\u3002" if language == "zh" else f"{stage} is running; I will verify the Data Tree and viewer output when it finishes."
        if status == "done":
            return f"{stage} \u5df2\u5b8c\u6210\uff1b\u8bf7\u5148\u6838\u5bf9 Data Tree \u548c viewer \u8f93\u51fa\uff0c\u518d\u7ee7\u7eed\u4e0b\u4e00\u6b65\u3002" if language == "zh" else f"{stage} completed; verify the Data Tree and viewer output before the next prerequisite step."
        if status == "error":
            return f"{stage} \u6267\u884c\u5931\u8d25\uff1b\u8bf7\u68c0\u67e5\u9519\u8bef\u8be6\u60c5\u5e76\u786e\u8ba4\u8f93\u5165\u6570\u636e\u3002" if language == "zh" else f"{stage} failed; inspect the error details and confirm the input data."
        return f"\u5df2\u8bb0\u5f55 {stage} \u4e8b\u4ef6\uff1b\u8bf7\u6838\u5bf9 Data Tree \u8f93\u51fa\u3002" if language == "zh" else f"{stage} event recorded; verify its Data Tree output."
    if event_type == "manual.dose":
        if v100 is not None and d90 is not None:
            return _localize_monitor_text(
                f"Dose preview updated: V100={v100 * 100:.1f}%, D90={d90:.1f} Gy. Review hot spots and OAR dose before adding seeds.",
                language,
            )
        return _localize_monitor_text("Dose preview updated. Open Analysis to inspect DVH and OAR dose.", language)
    return None


def _training_feedback_for_event(agent, session_id: Optional[str], event: Dict[str, Any], *, snapshot=None, return_pair=False):
    """Generate feedback once, then derive the requested language from that source."""
    from web import server_support as support
    detail = support._monitor_event_detail(event)
    language = support._monitor_language(event.get("language") or detail.get("language"))
    source_event = dict(event)
    source_event["language"] = "en"
    source_event["detail"] = {**detail, "language": "en"}
    raw = _training_feedback_for_event_source(agent, session_id, source_event, snapshot=snapshot)
    localized = _localize_monitor_text(raw, language) if raw is not None else None
    if return_pair:
        return {"raw": raw, "localized": localized}
    return localized


def _training_screenshot_for_event(agent, session_id: Optional[str], event: Dict[str, Any], feedback: Optional[str], *, snapshot=None) -> Optional[Dict[str, Any]]:
    from web import server_support as support
    if not feedback:
        return None
    event_type = str(event.get("type", ""))
    detail = support._monitor_event_detail(event)
    language = support._monitor_language(event.get("language") or detail.get("language"))
    if event_type in {"planning.step", "segmentation.step"} and support._monitor_event_status(event) != "done":
        return None
    if event_type in {"planning.error", "segmentation.error"}:
        return None
    snapshot = snapshot if snapshot is not None else support._latest_plan_snapshot(agent, validate_obstacles=False)
    metrics = snapshot.get("metrics", {}) or {}
    v100 = support._volume_metric_as_fraction(metrics, "v100")
    v200 = support._volume_metric_as_fraction(metrics, "v200")
    criteria = support._source_backed_target_context(agent).get("criteria", {})
    v100_min = support._metric_as_fraction(support._extract_metric_value(criteria, "v100_min"))
    v200_max = support._metric_as_fraction(support._extract_metric_value(criteria, "v200_max"))
    focus_ids = []
    for pair in (snapshot.get("seed_interference", {}) or {}).get("close_pairs", [])[:4]:
        for key in ("first_id", "second_id"):
            seed_id = str(pair.get(key) or "").strip()
            if seed_id and seed_id not in focus_ids:
                focus_ids.append(seed_id)
    def question(zh: str, en: str) -> str:
        return zh if language == "zh" else en
    if event_type == "manual.dose":
        concern = (v100 is not None and v100_min is not None and v100 < v100_min) or (v200 is not None and v200_max is not None and v200 > v200_max)
        result = {
            "target": "dose-overview" if concern else "dvh",
            "question": question(
                "\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u624b\u52a8\u5242\u91cf\u91cd\u7b97\u540e\u7684 CT\u3001\u63a9\u819c\u3001\u5242\u91cf\u70ed\u56fe\u3001\u7c92\u5b50\u3001\u9488\u9053\u548c DVH\u3002" if concern else "\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u624b\u52a8\u5242\u91cf\u91cd\u7b97\u540e\u7684 DVH\u3002",
                "Training monitor snapshot: show the CT, masks, dose heatmap, seeds/needles, and DVH after manual dose recomputation." if concern else "Training monitor snapshot: show the updated DVH after manual dose recomputation.",
            ),
        }
        return result
    if event_type == "segmentation.step":
        return {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u65b0\u52a0\u8f7d\u7684 CTV/OAR \u7ed3\u6784\u3001 3D \u67e5\u770b\u5668\u548c Data Tree\u3002", "Training monitor snapshot: show the newly loaded CTV/OAR structures in the 3D viewer and Data Tree.")}
    if event_type == "planning.step":
        key = support._monitor_step_key(event)
        if key in {"trajectory_init", "trajectory_refine", "seed_planning"}:
            stage = _monitor_step_label(key, language)
            return {"target": "viewer-3d", "question": question(f"\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a {stage} \u5b8c\u6210\u540e\u7684 3D \u67e5\u770b\u5668\u3001\u9488\u9053\u3001\u7c92\u5b50\u548c Data Tree\u3002", f"Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after {_monitor_step_label(key)}.")}
        if key in {"dose_calc", "dose_eval", "full"}:
            return {"target": "dose-overview", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u89c4\u5212\u5b8c\u6210\u540e\u7684\u5242\u91cf\u5206\u5e03\u548c DVH\u3002", "Training monitor snapshot: show the completed plan dose distribution and DVH for review.")}
        return None
    if event_type.startswith("manual.needle"):
        return {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u5f53\u524d 3D \u9488\u9053\u548c\u9644\u8fd1\u7684\u89e3\u5256\u7ed3\u6784\u3002", "Training monitor snapshot: show the current 3D needle path and nearby anatomy.")}
    if event_type.startswith("manual.seed"):
        result = {"target": "viewer-3d", "question": question("\u76d1\u6d4b\u622a\u56fe\uff1a\u663e\u793a\u88ab\u7f16\u8f91\u7684\u7c92\u5b50\u53ca\u5176\u90bb\u8fd1\u7c92\u5b50\uff0c\u7528\u4e8e\u68c0\u67e5\u95f4\u8ddd\u3002", "Training monitor snapshot: show the edited seed and nearby seeds so spacing can be checked.")}
        if focus_ids:
            result["focus_seed_ids"] = focus_ids
        return result
    return None
