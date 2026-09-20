"""Whole-utterance contracts for bypassing primary semantic interpretation.

Legacy detectors propose candidates; only an entire accepted command grants a
shortcut. Unknown syntax is an abstention, never a guessed operation. This
module must not inspect quoted instructions or invent actions from nouns.
"""
import re

P = r"(?:(?:请|帮我|麻烦|现在|立即)\s*)*"
EP = r"(?:please\s+)?"
PLAN = r"(?:放射性粒子植入|粒子植入|手术|治疗)?(?:规划|计划)"
GUIDE = r"(?:手术|穿刺)?导板"
OBJECT = r"(?:手术导板|穿刺导板|导板|ctv|oar|肿瘤|靶区|粒子|针道|穿刺针|surgical guide|puncture guide|seeds?|needles?|trajectories)"


def normalized(message):
    return re.sub(r"\s+", " ", str(message or '').strip().lower()).strip(' 。.!！?？')


def full(pattern, text):
    return re.fullmatch(pattern, text, re.IGNORECASE) is not None


def explicit_segmentation_request(message):
    text = normalized(message)
    if len(text) > 300:
        return False
    anatomy = r"(?:肝脏?|胰腺|肺|肾脏?|前列腺|头颈)"
    upload = r"(?:你好[,，])?我上传了(?:一名)?" + anatomy + r"(?:肿瘤|癌)患者(?:的)?ct[,，]"
    explicit_site = (
        r"(?:pancreatic|pancreas|hepatic|liver|renal|kidney|pulmonary|lung|"
        r"colorectal|colon|prostate|head\s*(?:and|&)\s*neck|head[-\s]+neck|"
        r"nasopharynx|nasopharyngeal)"
    )
    explicit_site_ctv = (
        EP + r"segment\s+(?:(?:the\s+)?(?:ctv|gtv)\s+(?:for|of)\s+)?"
        + r"(?:(?:a|the)\s+)?" + explicit_site
        + r"(?:\s+(?:cancer|tumou?r|lesion))?"
        + r"(?:\s+(?:ctv|gtv))?"
        + r"(?:\s+(?:on\s+)?(?:ncct|cect|non[-\s]?contrast|"
        + r"contrast[-\s]?enhanced)(?:\s+ct)?)?"
    )
    return full(P + r"(?:再|重新)?(?:执行|启动)(?:一次)?\s*(?:ctv|oar)\s*分割", text) or full(
        r"(?:" + upload + r")?" + P + r"分割" + anatomy + r"和肿瘤", text
    ) or full(upload + P + r"分析肿瘤在哪[,，]有多大", text) or full(
        explicit_site_ctv, text
    )


def explicit_repeat(message):
    return full(P + r"忽略现有结果[,，]?\s*(?:再分割|再启动一次分割)", normalized(message))


def planning_command(message):
    text = normalized(message)
    if len(text) > 300:
        return False
    # A factual upload/parameter prefix may precede the command, but cannot
    # contain arbitrary instructions, explanations, negation or conditions.
    context = r"(?:(?:我上传了(?:一名)?(?:胰腺|肝脏|头颈|肺|前列腺)?肿瘤患者ct|我改了粒子植入参数)[,，]\s*)?"
    command = P + r"(?:重新|再次)?(?:执行|进行|开始|制定|重做|重跑)?" + PLAN
    followup = r"我是让你重新" + PLAN
    guide_tail = r"(?:(?:[,，]\s*(?:并)?|后再)(?:请)?(?:重新)?生成(?:新的)?" + GUIDE + r")?"
    return full(context + r"(?:" + command + r"|" + followup + r")" + guide_tail, text) or full(
        EP + r"(?:run|execute|start|perform|rerun|replan|re-plan)(?:\s+the)?(?:\s+(?:brachytherapy|treatment))?(?:\s+plan(?:ning)?)?", text
    )


def shortcut_supported(message, policy, *, pending_tumor_site=False, ui_state=None):
    text = normalized(message)
    if not text or len(text) > 300:
        return False
    intent = policy.intent
    if policy.action_plan is not None:
        return planning_command(text)
    if intent == 'multi_intent_query':
        parsed_subtasks = tuple(getattr(policy, "parsed_subtasks", ()) or ())
        safe_reads = {
            "planning_provenance_query", "planning_assessment_query",
            "case_state_question", "case_dose_query", "image_metadata_query",
            "current_oar_query", "session_visual_location_query",
            "surgical_guide_status_query", "code_capability_query",
            "ambiguous_visual_target_query", "unresolved_visual_target_query",
        }
        # Count subtasks, not distinct intent names: two independently
        # grounded visual-location questions are both read-only and must stay
        # separate so each can receive its own target-scoped screenshot.
        return (
            1 <= len(parsed_subtasks) <= 6
            and all(
                isinstance(item, (list, tuple))
                and len(item) >= 2
                and str(item[0]) in safe_reads
                for item in parsed_subtasks
            )
        )
    if intent == 'ambiguous_visual_target_query':
        # The live catalog proved that this label belongs to multiple objects.
        # Ask deterministically instead of letting a model guess an identity.
        return True
    if intent == 'surgical_guide_status_query':
        # This contract only reaches the read-only status action, never generate.
        return True
    if intent in {'clinical_planning', 'planning', 'treatment_plan'}:
        return planning_command(text)
    if intent == 'segmentation':
        if explicit_segmentation_request(text):
            return True
        if pending_tumor_site and full(r"胰腺|肝脏?|肺|肾脏?|前列腺|pancreas|liver|lung|kidney|prostate", text):
            return True
        site = (r"(?:肝脏?|胰腺|肺部?|肾脏?|前列腺|头颈部(?:肿瘤)?|鼻咽癌?|结肠|"
                r"pancreas|liver|lung|kidney|prostate|head and neck|nasopharynx|colon)")
        seg = r"(?:分割|勾画|勾勒)"
        return (
            full(P + r"(?:重新)?(?:执行|进行|开始)?\s*(?:ctv|oar)\s*" + seg, text)
            # "<verb> <site> [CTV]" and "<verb> CTV <site>" and "<site> CTV 分割".
            or full(P + r"(?:重新)?" + seg + r"\s*(?:ctv|oar)?\s*" + site
                    + r"(?:\s*(?:ctv|oar))?", text)
            or full(P + r"(?:重新)?" + site + r"\s*(?:ctv|oar)?\s*" + seg, text)
            or full(EP + r"(?:segment|delineate|outline)\s+(?:the\s+)?(?:ctv|oar|liver|pancreas|lung|kidney|prostate)", text)
        )
    if intent == 'surgical_guide_generation':
        return full(P + r"(?:重新)?(?:生成|制作|创建|更新|重建)" + GUIDE, text) or full(
            EP + r"(?:generate|regenerate|create|rebuild|update)\s+(?:the\s+)?(?:surgical |puncture )?guide", text)
    if intent == 'viewer_display':
        return full(P + r"(?:把|将)?(?:当前|已有|规划|的)*结果(?:在|到)(?:3d\s*|2d\s*)?(?:viewer|查看器)(?:中|里)?(?:显示|展示|加载)(?:出来)?(?:啊|吧)?", text) or full(
            EP + r"(?:show|display|load)\s+(?:the |current |planning )*results?\s+in\s+(?:the )?(?:3d |2d )?viewer", text)
    if intent == 'dose_recompute':
        if full(r"(?:可以|请)?重新计算(?:当前规划方案的)?dvh相关指标(?:[,，]验证和当前的结果是否一致)?", text) or full(
            EP + r"recalculate the current plan's dose and dvh metrics", text
        ):
            return True
        return full(P + r"(?:重新)?(?:计算|评估)(?:当前|规划|的|方案|剂量|dvh|和|与|\s)+", text) or full(
            EP + r"(?:recompute|recalculate|calculate)\s+(?:the |current )?(?:dose|dvh)(?:\s+and\s+(?:dose|dvh))?", text)
    if intent == 'session_visual_location_query':
        catalog = (ui_state or {}).get('visual_target_catalog') or []
        labels = [normalized(item.get('label')) for item in catalog
                  if isinstance(item, dict) and item.get('label')] if isinstance(catalog, list) else []
        obj = r"(?:" + OBJECT + r"|3d重建的按钮" + ''.join('|' + re.escape(label) for label in labels) + r")"
        prefix = r"(?:那\s*)?" + P + r"(?:请问|那)?(?:告诉我|告知我|说一下|说明)?(?:患者的|3d查看器里的)?(?:已生成的|生成的|当前的|当前)?"
        screenshot_suffix = (
            r"(?:[，,;；]\s*(?:(?:并|然后|再)\s*)?(?:请)?"
            r"(?:截图|截屏)(?:告知|说明|告诉我|给我看(?:看)?|展示|标注)?(?:一下)?)?"
        )
        # Context-dependent forms are accepted only after the candidate
        # resolver has found an unambiguous target from recent user context.
        return full(prefix + obj + r"(?:在)?(?:哪里|哪儿|在哪|的位置)(?:呢|呀|啊|吗)?" + screenshot_suffix, text) or full(
            r"(?:那\s*)?" + P + r"(?:截图|截屏)(?:告诉我|标出|标注|指出)" + r"(?:已生成的|生成的|当前的|当前)?" + obj + r"(?:在)?(?:哪里|哪儿|的位置)", text
        ) or full(P + r"(?:圈出|标出|指出)\s*" + obj + r"\s*(?:在哪里)?", text) or full(
            P + r"圈出来哪个是" + obj, text
        ) or full(r"(?:please )?(?:where is|where are|locate|find)\s+(?:the |current |generated )*" + obj, text) or text == '截图给我在哪里'
    if intent == 'ui_operation':
        if full(P + r"对(?:所有|全部)oar\s*mask进行3d\s*重建", text):
            return True
        # Typed, complete group commands. A catalogue score alone is not an
        # instruction; dynamic controls require exact complete label matching.
        if full(P + r"(?:把|将)?(?:所有|全部|当前)?(?:oar|ctv)(?:在)?(?:的)?(?:透明度)?(?:设为|设置为|调到|调整为)(?:半透明|透明|不透明|\d{1,3}%?)", text):
            return True
        if full(P + r"(?:显示|隐藏)(?:所有|全部)?(?:oar|ctv)", text):
            return True
        catalog = (ui_state or {}).get('ui_operation_catalog') or []
        if not isinstance(catalog, list):
            return False
        for entry in catalog:
            if not isinstance(entry, dict):
                continue
            label = normalized(entry.get('label'))
            if label and full(r"(?:" + P + r"(?:点击|按下)|" + EP + r"click\s+)" + re.escape(label), text):
                return True
        return False
    # Report/content policies already have their own full-command contracts.
    return intent == 'report_generation'
