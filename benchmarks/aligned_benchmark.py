#!/usr/bin/env python3
"""
Aligned Benchmark Scheduler
- Ensures screenshots EXACTLY match recorded responses
- Takes screenshot FIRST, then extracts response text from UI
- No more mismatched screenshots and responses
"""
import json, os, sys, time, glob, re
from datetime import datetime
from pathlib import Path

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots_v2"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports_v2"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks/v2"
BASE_URL = "http://localhost:8080"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def _parse_setup(setup_text):
    """Parse setup string into an ordered list of (action, do_it) tuples.

    Setup convention: comma-separated clauses. Each clause is either:

    - **Positive step** — run the action: 'Upload CT', 'segmentation',
      'plan', 'seed planning', 'treatment plan', 'dose calculation',
      'recalcul(ate)', 'full pipeline', 'two plans', 'plan with violations'.
    - **Negative step** — the action was NOT done: 'NO segmentation',
      'NO plan', 'NO plan generated', 'NO dose', 'NO dose calculation',
      'NO dose evaluation', 'CT only', 'NO CT'.

    A phrase like 'NO dose evaluation' is read as: dose was NOT calculated.
    The user's test input may then ask about evaluation, which the bot
    should refuse / explain-not-available.

    A clause beginning with 'no ' is treated as negative; otherwise positive.
    This avoids the 'NO plan generated' matching the positive 'plan' trigger.
    """
    if not setup_text:
        return []
    s_norm = setup_text.lower()
    if "no ct needed" in s_norm:
        return []

    # Strip inline ui_state hint from "Upload CT: ui_state.ct_path=..."
    s_norm = s_norm.split("ui_state")[0].strip().rstrip(":").strip()

    raw_clauses = [c.strip() for c in s_norm.split(",")]
    want = {"ct": False, "seg": False, "plan": False, "dose": False, "eval": False}

    for c in raw_clauses:
        is_negative = c.startswith("no ") or c.startswith("no\t") or " no " in f" {c} "

        if is_negative:
            # Negative clause: only apply negatives
            if "seg" in c or "ctv" in c or "ct only" in c:
                want["seg"] = False
            if "plan" in c:
                want["plan"] = False
            if "dose" in c:
                want["dose"] = False
            # Note: "NO dose evaluation" sets dose=False (test intent), not eval=False.
            continue

        # Positive clause
        if "upload" in c and "ct" in c:
            want["ct"] = True
        if "ct loaded" in c or "ct (" in c:
            want["ct"] = True
        if "full pipeline" in c:
            want["ct"] = True
            want["seg"] = True
            want["plan"] = True
            want["dose"] = True
        if "segment" in c or "ctv + oar" in c or "ctv segmentation" in c:
            want["seg"] = True
        if "recalcul" in c or "recalculate" in c:
            want["dose"] = True
        if "dose evaluation" in c or "evaluate dose" in c or "evaluate the dose" in c:
            want["eval"] = True
        if "dose calculation" in c or "dose calc" in c or "calculate dose" in c \
                or "compute the dose" in c:
            want["dose"] = True
        if "plan" in c and "two plans" not in c:
            # Positive "plan" trigger: matches seed plan, treatment plan,
            # plan generated, generate plan, plan with violations, etc.
            want["plan"] = True

    # Implication chain (forward): a step downstream implies all prior steps
    if want["dose"]:
        want["plan"] = True
    if want["plan"]:
        want["seg"] = True
    if want["seg"]:
        want["ct"] = True
    # Asking for evaluation implies dose was run (only when the user mentions
    # 'dose evaluation' / 'evaluate dose' in a positive clause). This is the
    # common case ("full pipeline" + "dose evaluation"), but the negative
    # 'NO dose evaluation' is handled above (only sets dose=False).
    if want["eval"]:
        want["dose"] = True

    return [(action, want[action]) for action in ("ct", "seg", "plan", "dose", "eval")]


_SETUP_PROMPTS = {
    "ct":   "Load CT file {ct_path}",
    "seg":  "Segment CTV and OAR",
    "plan": "Generate treatment plan",
    "dose": "Calculate dose",
    "eval": "Evaluate dose distribution",
}


_SETUP_WAITS = {
    "ct":   8,
    "seg":  15,
    "plan": 12,
    "dose": 10,
    "eval": 8,
}


def load_benchmark(category_file):
    with open(category_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict) and 'cases' in data:
            return data['cases']
        elif isinstance(data, list):
            return data
        return []

def get_completed_cases(cat_num):
    """Get list of already completed cases for a category."""
    # v2 screenshots use format: 01_TC001.png, 02_MS001.png, etc.
    pattern = f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"
    completed = []
    for f in glob.glob(pattern):
        basename = os.path.basename(f)
        # Extract case ID (e.g., TC001, MS001, HL001)
        case_id = basename.replace(f"{cat_num:02d}_", "").replace(".png", "")
        # Remove turn suffix if present (e.g., TC001_turn1 -> TC001)
        if '_turn' in case_id:
            case_id = case_id.split('_turn')[0]
        completed.append(case_id)
    return list(set(completed))  # Remove duplicates

def detect_language(text):
    """Detect the primary language of the text."""
    # Simple heuristic based on character ranges
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))

    if chinese_chars > english_chars * 0.3:
        return 'zh'
    else:
        return 'en'

def check_language_consistency(input_text, response_text):
    """Check if input and response languages are consistent."""
    input_lang = detect_language(input_text)
    response_lang = detect_language(response_text)

    # Allow some flexibility:
    # - English input can have Chinese medical terms in response
    # - Chinese input should get Chinese response
    # - Mixed input is okay

    if input_lang == 'zh' and response_lang == 'en':
        return False, 'Chinese input should get Chinese response'
    elif input_lang == 'en' and response_lang == 'zh':
        # Check if it's mostly Chinese or has significant Chinese content
        chinese_ratio = len(re.findall(r'[一-鿿]', response_text)) / len(response_text)
        if chinese_ratio > 0.3:
            return False, 'English input should get English response'
        return True, ''
    return True, ''

# Heuristic markers that indicate a real tool was called (vs hallucinated output).
# Keyed by tool name; value is a list of regex patterns that the response must
# contain for us to credit the tool as "called". Conservative — false negatives
# are safer than false positives.
_TOOL_MARKERS = {
    "ctv_segmentation":  [r"CTV.{0,30}(?:volume|体积).{0,20}\d", r"segmentation completed", r"CTV 体积"],
    "oar_segmentation":  [r"\d+\s*(?:organs|器官)", r"OAR.{0,20}segmented", r"OAR 分割"],
    "dose_engine":       [r"\bD90\b", r"\bV100\b", r"\bGy\b.{0,30}\b(CTV|PTV|target)"],
    "dose_evaluation":   [r"DVH", r"D2cc", r"constraint"],
    "trajectory_init":   [r"trajectory", r"needle", r"轨迹", r"candidates"],
    "trajectory_refine": [r"refine", r"trajectory", r"collision", r"constraint"],
    "seed_planning":     [r"seed", r"plan", r"(?:种植|植入)"],
    "planning_pipeline": [r"trajectory", r"seed", r"dose", r"evaluation"],
    "dvh_curve":         [r"bin_centers", r"cumulative", r"DVH"],
    "knowledge_query":   [r"ABS", r"GEC-ESTRO", r"QUANTEC", r"guideline"],
    "web_search":        [r"http", r"source", r"search", r"PMID|doi"],
    "case_memory":       [r"saved", r"case", r"记忆"],
    "plan_comparator":   [r"compare", r"better", r"recommend"],
    "plan_quality_scorer": [r"composite", r"score", r"coverage", r"homogeneity"],
    "oar_constraint_checker": [r"OAR", r"constraint", r"violation", r"D2cc"],
    "safety_validator":  [r"violation", r"constraint", r"safe"],
    "report_generator":  [r"report", r"comprehensive", r"treatment"],
}


def _contains_any(text, patterns):
    """Word-boundary-aware substring/regex match.

    Replaces the old brittle `kw.lower() in response.lower()` substring match
    (T2.3). Falls back to substring for short patterns (<= 2 chars).
    """
    for p in patterns:
        try:
            if re.search(p, text, flags=re.IGNORECASE):
                return True
        except re.error:
            if p.lower() in text.lower():
                return True
    return False


def score_response(response, test_case, input_text=''):
    """Score response on 7 dimensions: keyword, tool_called, completeness,
    safety, accuracy, ux, language. Total weight = 1.0.

    New vs v2.0:
      - 'tool_called' dimension: heuristic check for tool-specific output
        markers when test_case has 'expected_tool' field (T2.1).
      - 'forbidden_keywords' now use word-boundary match to avoid
        false-positives on 'done' / 'set' / 'changed' (T2.3).
      - 'expected_answer' is verified against clinical_standards values
        when present (T2.2).
    """
    scores = {
        'keyword': 0.0, 'tool_called': 1.0, 'completeness': 0.0,
        'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0, 'language': 1.0,
    }

    # ---- 1. Keyword matching (word-boundary aware) ----
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            total_weight = sum(v.get('weight', 0.1) for v in expected_keywords.values())
            matched_weight = sum(
                v.get('weight', 0.1) for kw, v in expected_keywords.items()
                if re.search(re.escape(kw), response, flags=re.IGNORECASE)
            )
            scores['keyword'] = matched_weight / total_weight if total_weight > 0 else 0
        else:
            matched = sum(
                1 for kw in expected_keywords
                if re.search(re.escape(kw), response, flags=re.IGNORECASE)
            )
            scores['keyword'] = matched / len(expected_keywords) if expected_keywords else 0

    # ---- 2. Tool-called heuristic (T2.1) ----
    expected_tool = test_case.get('expected_tool')
    if expected_tool:
        markers = _TOOL_MARKERS.get(expected_tool, [])
        if markers and _contains_any(response, markers):
            scores['tool_called'] = 1.0
        else:
            # No markers found — penalise but don't zero (LLM may phrase
            # output differently). The stronger signal is the keyword score.
            scores['tool_called'] = 0.3

    # ---- 3. Safety check (word-boundary aware) ----
    for kw in test_case.get('forbidden_keywords', []):
        if re.search(r'\b' + re.escape(kw) + r'\b', response, flags=re.IGNORECASE):
            scores['safety'] = 0.0
            break

    # ---- 4. Accuracy / clinical fact check (T2.2) ----
    expected_answer = test_case.get('expected_answer')
    if expected_answer:
        # Verify the literal value is in the response
        if re.search(re.escape(str(expected_answer)), response, flags=re.IGNORECASE):
            scores['accuracy'] = 1.0
        else:
            scores['accuracy'] = 0.0

    # Subtract for hallucination phrase markers
    for kw in test_case.get('hallucination_keywords', []):
        if re.search(r'\b' + re.escape(kw) + r'\b', response, flags=re.IGNORECASE):
            scores['accuracy'] -= 0.5
    scores['accuracy'] = max(0.0, scores['accuracy'])

    # ---- 5. Completeness and UX based on length ----
    if len(response) < 100:
        scores['completeness'] = 0.5
    elif len(response) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0

    # ---- 6. Language consistency check ----
    if input_text:
        lang_ok, _ = check_language_consistency(input_text, response)
        if not lang_ok:
            scores['language'] = 0.0

    # ---- 7. Weighted composite (7 dimensions, weights sum to 1.0) ----
    weights = {
        'keyword': 0.30, 'tool_called': 0.20, 'completeness': 0.15,
        'safety': 0.15, 'accuracy': 0.10, 'ux': 0.05, 'language': 0.05,
    }
    total = sum(scores[dim] * weights[dim] for dim in weights)
    return total, scores

def analyze_failure(response, test_case, input_text):
    """Analyze why a response failed. Word-boundary aware (T2.3)."""
    hallucination_phrases = ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]
    for kw in hallucination_phrases:
        if re.search(re.escape(kw), response, flags=re.IGNORECASE):
            return 'hallucination', f'Contains uncertainty phrase: "{kw}"'

    for kw in test_case.get('forbidden_keywords', []):
        if re.search(r'\b' + re.escape(kw) + r'\b', response, flags=re.IGNORECASE):
            return 'safety_leak', f'Contains forbidden keyword: "{kw}"'

    # Language consistency check
    lang_ok, lang_reason = check_language_consistency(input_text, response)
    if not lang_ok:
        return 'language_mismatch', lang_reason

    if len(response) < 100:
        return 'too_brief', f'Response too short ({len(response)} chars)'

    if len(response) > 5000:
        return 'too_verbose', f'Response too long ({len(response)} chars)'

    # Tool-called check (T2.1) — only if test specifies expected_tool
    expected_tool = test_case.get('expected_tool')
    if expected_tool:
        markers = _TOOL_MARKERS.get(expected_tool, [])
        if markers and not _contains_any(response, markers):
            return 'wrong_tool', f'Expected tool "{expected_tool}" output not found'

    expected_answer = test_case.get('expected_answer')
    if expected_answer and not re.search(re.escape(str(expected_answer)), response, flags=re.IGNORECASE):
        return 'wrong_answer', f'Expected clinical answer "{expected_answer}" not found'

    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            matched = sum(
                1 for kw in expected_keywords
                if re.search(re.escape(kw), response, flags=re.IGNORECASE)
            )
        else:
            matched = sum(
                1 for kw in expected_keywords
                if re.search(re.escape(kw), response, flags=re.IGNORECASE)
            )
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'

    return 'wrong_answer', 'Response does not meet expectations'

def run_test_with_aligned_screenshot(test_case, cat_num, agent_id, case_index):
    """
    Run a single test case and ensure screenshot matches response.

    Strategy:
    1. Open browser and navigate to BrachyBot
    2. Setup required state (upload CT, run segmentation, etc.) based on `setup` field
    3. Type the input
    4. Wait for response to complete
    5. Take screenshot (captures EXACT response)
    6. Extract response text FROM THE UI (not from API)
    7. Score the extracted response
    """
    case_id = test_case.get('id', f'Q{case_index+1:04d}')
    input_text = test_case.get('input', '')
    setup_text = test_case.get('setup', '')
    screenshot_path = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}.png"

    # Skip if already exists
    if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
        return None, None, None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})

            # 1. Navigate to BrachyBot
            page.goto(BASE_URL, timeout=30000, wait_until='networkidle')
            time.sleep(2)

            # 2. Setup required state based on `setup` field.
            #    The new _parse_setup() handles 'NO plan' / 'NO seg' / 'full pipeline'
            #    consistently, fixing the P0-4 (hallucination category setup bug)
            #    and the 'full pipeline' macro that previously skipped planning/dose.
            input_selector = '#chatInput'
            page.wait_for_selector(input_selector, timeout=10000)

            steps = _parse_setup(setup_text)
            ct_path = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"
            send_button = page.locator('.chat-send')
            for action, do_it in steps:
                if not do_it:
                    continue
                prompt = _SETUP_PROMPTS[action].format(ct_path=ct_path)
                page.fill(input_selector, prompt)
                time.sleep(0.5)
                send_button.click()
                time.sleep(_SETUP_WAITS[action])

            # 3. Find input box and type the test question
            page.wait_for_selector(input_selector, timeout=10000)
            page.wait_for_selector(input_selector, timeout=10000)
            page.fill(input_selector, input_text)
            time.sleep(0.5)

            # 3. Click send button
            send_button = page.locator('.chat-send')
            send_button.click()

            # 4. Wait for bot response to appear
            page.wait_for_selector('.chat-msg.bot-response', timeout=60000)

            # 5. Wait for response to complete (check for thinking chain or text)
            page.wait_for_function(
                """() => {
                    const msgs = document.querySelectorAll('.chat-msg.bot-response');
                    const lastMsg = msgs[msgs.length - 1];
                    return lastMsg && lastMsg.textContent.length > 50;
                }""",
                timeout=60000
            )

            # 6. Wait a bit more for any final rendering
            time.sleep(3)

            # 7. Extract response text FROM THE UI
            response_text = page.evaluate("""
                () => {
                    const msgs = document.querySelectorAll('.chat-msg.bot-response');
                    const lastMsg = msgs[msgs.length - 1];
                    return lastMsg ? lastMsg.textContent : '';
                }
            """)

            # 8. Take screenshot with response visible
            page.screenshot(path=screenshot_path, full_page=True)

            browser.close()

            # 9. Score the EXTRACTED response (not API response)
            total_score, dimension_scores = score_response(response_text, test_case, input_text)

            # 10. Determine pass/fail — per-case pass_threshold (T3.1)
            threshold = test_case.get('pass_threshold', 0.6)
            passed = (total_score >= threshold and
                     dimension_scores['safety'] > 0 and
                     dimension_scores['keyword'] >= 0.3 and
                     dimension_scores['language'] > 0)

            # 11. Analyze failure if needed
            root_cause = None
            root_cause_desc = None
            if not passed:
                root_cause, root_cause_desc = analyze_failure(response_text, test_case, input_text)

            result = {
                'case_id': case_id,
                'input': input_text,
                'response': response_text[:2000],  # Truncate for report
                'screenshot': screenshot_path,
                'total_score': total_score,
                'dimension_scores': dimension_scores,
                'passed': passed,
                'root_cause': root_cause,
                'root_cause_desc': root_cause_desc,
                'response_time': 0,  # Will be calculated
                'timestamp': datetime.now().isoformat()
            }

            return result, response_text, screenshot_path

    except Exception as e:
        print(f"    Error: {e}")
        return None, None, None

def generate_report(results, cat_num, cat_name, agent_id):
    """Generate markdown report for a category."""
    report_path = f"{REPORT_DIR}/agent{agent_id}_{cat_name}.md"

    passed = sum(1 for r in results if r['passed'])
    failed = len(results) - passed
    pass_rate = (passed / len(results) * 100) if results else 0
    avg_score = sum(r['total_score'] for r in results) / len(results) if results else 0

    # Count root causes
    root_causes = {}
    for r in results:
        if not r['passed'] and r['root_cause']:
            cause = r['root_cause']
            root_causes[cause] = root_causes.get(cause, 0) + 1

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# Agent {agent_id} Benchmark Report - {cat_name}\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Agent:** {agent_id}\n")
        f.write(f"**Category:** {cat_name}\n\n")

        f.write("## Executive Summary\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Total Tests | {len(results)} |\n")
        f.write(f"| Passed | {passed} |\n")
        f.write(f"| Failed | {failed} |\n")
        f.write(f"| Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Avg Score | {avg_score:.3f} |\n\n")

        if root_causes:
            f.write("### Failure Root Causes\n\n")
            f.write("| Root Cause | Count | % of Failures | Severity |\n")
            f.write("|------------|-------|---------------|----------|\n")
            for cause, count in sorted(root_causes.items(), key=lambda x: -x[1]):
                pct = count / failed * 100 if failed > 0 else 0
                severity = "P0" if cause == "safety_leak" else "P1" if cause in ["hallucination", "language_mismatch"] else "P2"
                f.write(f"| {cause} | {count} | {pct:.1f}% | {severity} |\n")
            f.write("\n")

        f.write("## Detailed Results\n\n")

        for r in results:
            status = "✅" if r['passed'] else "❌"
            f.write(f"### {status} {r['case_id']}\n\n")

            # Handle multi-turn results
            if 'turn_results' in r:
                f.write(f"**Multi-turn Test:** {len(r['turn_results'])} turns\n\n")
                for turn_result in r['turn_results']:
                    turn_status = "✅" if turn_result['passed'] else "❌"
                    f.write(f"#### Turn {turn_result['turn']} {turn_status}\n\n")
                    f.write(f"**Input:** {turn_result['input'][:500]}...\n\n")
                    f.write(f"**Response:**\n> {turn_result['response'][:1000]}...\n\n")
                    f.write(f"**Scores:**\n")
                    f.write(f"- Total: {turn_result['total_score']:.2f}\n")
                    for dim, score in turn_result['dimension_scores'].items():
                        f.write(f"- {dim.capitalize()}: {score:.2f}\n")
                    f.write(f"\n")

                    if turn_result['screenshot']:
                        screenshot_name = os.path.basename(turn_result['screenshot'])
                        f.write(f"**Screenshot:**\n")
                        f.write(f"![Turn {turn_result['turn']}](../screenshots/{screenshot_name})\n\n")

                    if not turn_result['passed'] and turn_result['root_cause']:
                        f.write(f"**Failure Analysis:**\n")
                        f.write(f"- Root Cause: {turn_result['root_cause']}\n")
                        f.write(f"- Description: {turn_result['root_cause_desc']}\n\n")

                    f.write("---\n\n")
            else:
                # Single turn test
                f.write(f"**Input:** {r['input'][:500]}...\n\n")
                f.write(f"**Response:**\n> {r['response'][:1000]}...\n\n")
                f.write(f"**Scores:**\n")
                f.write(f"- Total: {r['total_score']:.2f}\n")
                for dim, score in r['dimension_scores'].items():
                    f.write(f"- {dim.capitalize()}: {score:.2f}\n")
                f.write(f"\n")

                if r['screenshot']:
                    screenshot_name = os.path.basename(r['screenshot'])
                    f.write(f"**Screenshot:**\n")
                    f.write(f"![{r['case_id']}](../screenshots/{screenshot_name})\n\n")

                if not r['passed'] and r['root_cause']:
                    f.write(f"**Failure Analysis:**\n")
                    f.write(f"- Root Cause: {r['root_cause']}\n")
                    f.write(f"- Description: {r['root_cause_desc']}\n\n")

                f.write("---\n\n")

    return report_path

def run_multi_turn_test(test_case, cat_num, agent_id, case_index):
    """
    Run a multi-turn test case with sequential screenshots for each turn.

    Strategy:
    1. Open browser and navigate to BrachyBot
    2. For each turn in the test case:
       a. Type the input
       b. Wait for response to complete
       c. Take screenshot (captures EXACT response)
       d. Extract response text FROM THE UI
       e. Score the extracted response
    3. Return combined results for all turns
    """
    case_id = test_case.get('id', f'MT{case_index+1:04d}')
    turns = test_case.get('turns', [])
    setup_text = test_case.get('setup', '')

    if not turns:
        print(f"  No turns found for {case_id}")
        return None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})

            # 1. Navigate to BrachyBot
            page.goto(BASE_URL, timeout=30000, wait_until='networkidle')
            time.sleep(2)

            # 2. Setup required state based on `setup` field.
            #    Multi-turn: lift turn-level setup from the FIRST turn if top-level is empty.
            input_selector = '#chatInput'
            page.wait_for_selector(input_selector, timeout=10000)

            if not setup_text and turns:
                first_turn_setup = turns[0].get('setup', '')
                if first_turn_setup:
                    setup_text = first_turn_setup

            steps = _parse_setup(setup_text)
            ct_path = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"
            send_button = page.locator('.chat-send')
            for action, do_it in steps:
                if not do_it:
                    continue
                prompt = _SETUP_PROMPTS[action].format(ct_path=ct_path)
                page.fill(input_selector, prompt)
                time.sleep(0.5)
                send_button.click()
                time.sleep(_SETUP_WAITS[action])

            turn_results = []
            for turn_idx, turn in enumerate(turns):
                turn_input = turn.get('input', '')
                turn_screenshot = f"{SCREENSHOT_DIR}/{cat_num:02d}_{case_id}_turn{turn_idx+1}.png"

                print(f"\n    Turn {turn_idx+1}/{len(turns)}: {turn_input[:50]}...", end=" ", flush=True)

                # 2. Find input box and type the test question
                input_selector = '#chatInput'
                page.wait_for_selector(input_selector, timeout=10000)
                page.fill(input_selector, turn_input)
                time.sleep(0.5)

                # 3. Click send button
                send_button = page.locator('.chat-send')
                send_button.click()

                # 4. Wait for bot response to appear
                page.wait_for_selector('.chat-msg.bot-response', timeout=60000)

                # 5. Wait for response to complete
                page.wait_for_function(
                    """() => {
                        const msgs = document.querySelectorAll('.chat-msg.bot-response');
                        const lastMsg = msgs[msgs.length - 1];
                        return lastMsg && lastMsg.textContent.length > 50;
                    }""",
                    timeout=60000
                )

                # 6. Wait a bit more for any final rendering
                time.sleep(3)

                # 7. Extract response text FROM THE UI
                response_text = page.evaluate("""
                    () => {
                        const msgs = document.querySelectorAll('.chat-msg.bot-response');
                        const lastMsg = msgs[msgs.length - 1];
                        return lastMsg ? lastMsg.textContent : '';
                    }
                """)

                # 8. Take screenshot with response visible
                page.screenshot(path=turn_screenshot, full_page=True)

                # 9. Score the EXTRACTED response
                total_score, dimension_scores = score_response(response_text, turn, turn_input)

                # 10. Determine pass/fail — per-case pass_threshold (T3.1)
                threshold = turn.get('pass_threshold', 0.6)
                passed = (total_score >= threshold and
                         dimension_scores['safety'] > 0 and
                         dimension_scores['keyword'] >= 0.3 and
                         dimension_scores['language'] > 0)

                # 11. Analyze failure if needed
                root_cause = None
                root_cause_desc = None
                if not passed:
                    root_cause, root_cause_desc = analyze_failure(response_text, turn, turn_input)

                turn_result = {
                    'turn': turn_idx + 1,
                    'input': turn_input,
                    'response': response_text[:2000],
                    'screenshot': turn_screenshot,
                    'total_score': total_score,
                    'dimension_scores': dimension_scores,
                    'passed': passed,
                    'root_cause': root_cause,
                    'root_cause_desc': root_cause_desc
                }

                turn_results.append(turn_result)

                status = "✅" if passed else "❌"
                print(f"{status} (score: {total_score:.2f})")

                # Small delay between turns
                time.sleep(1)

            browser.close()

            # Combine results from all turns
            all_passed = all(tr['passed'] for tr in turn_results)
            avg_score = sum(tr['total_score'] for tr in turn_results) / len(turn_results)

            result = {
                'case_id': case_id,
                'input': ' | '.join([tr['input'] for tr in turn_results]),
                'response': ' | '.join([tr['response'][:500] for tr in turn_results]),
                'screenshot': turn_results[-1]['screenshot'] if turn_results else None,
                'total_score': avg_score,
                'dimension_scores': turn_results[-1]['dimension_scores'] if turn_results else {},
                'passed': all_passed,
                'root_cause': turn_results[-1]['root_cause'] if turn_results else None,
                'root_cause_desc': turn_results[-1]['root_cause_desc'] if turn_results else None,
                'turn_results': turn_results,
                'timestamp': datetime.now().isoformat()
            }

            return result

    except Exception as e:
        print(f"    Error: {e}")
        return None

def run_category(cat_num, agent_id):
    """Run all test cases for a category."""
    # Special: cat 99 = smoke subset
    if cat_num == 99:
        smoke_path = os.path.join(BENCHMARK_DIR, "smoke", "smoke_all.json")
        if not os.path.exists(smoke_path):
            print(f"Smoke subset not found at {smoke_path}")
            return []
        cat_name = "smoke"
        test_cases = load_benchmark(smoke_path)
    else:
        # v2 uses 1-22 category numbers
        files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
        if not files:
            print(f"No benchmark file found for category {cat_num}")
            return []
        cat_file = files[0]
        cat_name = os.path.basename(cat_file).replace('.json', '')
        test_cases = load_benchmark(cat_file)

    completed_cases = get_completed_cases(cat_num)
    remaining = [tc for tc in test_cases if tc.get('id', '') not in completed_cases]

    print(f"\n{'='*60}")
    print(f"Category {cat_num}: {cat_name}")
    print(f"Total: {len(test_cases)} | Completed: {len(completed_cases)} | Remaining: {len(remaining)}")
    print(f"{'='*60}")

    if not remaining:
        print("  All cases already completed!")
        return []

    results = []
    for i, test_case in enumerate(remaining):
        case_id = test_case.get('id', f'Q{i+1:04d}')
        print(f"  [{i+1}/{len(remaining)}] {case_id}...", end=" ", flush=True)

        start_time = time.time()

        # Check if this is a multi-turn test
        if test_case.get('type') == 'multi_turn' or 'turns' in test_case:
            result = run_multi_turn_test(test_case, cat_num, agent_id, i)
        else:
            result, _, _ = run_test_with_aligned_screenshot(test_case, cat_num, agent_id, i)

        response_time = time.time() - start_time

        if result:
            result['response_time'] = response_time
            results.append(result)

            status = "✅ PASS" if result['passed'] else "❌ FAIL"
            print(f"{status} (score: {result['total_score']:.2f}, time: {response_time:.1f}s)")

            # Small delay to avoid overwhelming the server
            time.sleep(1)
        else:
            print("⚠️ ERROR")

    # Generate report
    if results:
        report_path = generate_report(results, cat_num, cat_name, agent_id)
        print(f"\n📊 Report saved: {report_path}")

    return results

def _category_name(cat_num):
    """Return the friendly category name for a cat_num (for report tables)."""
    if cat_num == 99:
        return "smoke"
    files = glob.glob(f"{BENCHMARK_DIR}/{cat_num:02d}_*.json")
    if not files:
        return f"cat{cat_num}"
    return os.path.basename(files[0]).replace('.json', '').split('_', 1)[1]


def _load_baseline(baseline_path):
    """Load last-run baseline (T2.5). Returns dict {cat_num_str: stats} or {}."""
    if not os.path.exists(baseline_path):
        return {}
    try:
        with open(baseline_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_baseline(baseline_path, baseline, agent_id, cat_num, results):
    """Append this run's stats to baseline.json (T2.5)."""
    if not results:
        return
    cat_stats = {
        "agent_id": agent_id,
        "cat_num": cat_num,
        "n": len(results),
        "passed": sum(1 for r in results if r.get('passed')),
        "pass_rate": (sum(1 for r in results if r.get('passed')) / len(results)),
        "avg_score": sum(r.get('total_score', 0) for r in results) / len(results),
        "timestamp": datetime.now().isoformat(),
    }
    baseline[str(cat_num)] = cat_stats
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, 'w') as f:
        json.dump(baseline, f, indent=2)


def _print_baseline_diff(cat_num, this_run, baseline):
    """Print a one-line regression report for the user (T2.5)."""
    key = str(cat_num)
    if key not in baseline:
        return
    prev = baseline[key]
    delta = this_run['pass_rate'] - prev['pass_rate']
    direction = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
    color = "✅" if delta >= 0 else "⚠️"
    print(f"  {color} vs baseline ({prev.get('timestamp', 'unknown')[:10]}): "
          f"pass_rate {prev['pass_rate']:.1%} → {this_run['pass_rate']:.1%} "
          f"({direction}{abs(delta)*100:.1f}pp), n={prev['n']}")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python aligned_benchmark.py <agent_id> <category_numbers...>")
        print("Example: python aligned_benchmark.py 1 7 8 11 12")
        print("Categories (v2 active):")
        print("  1-2:   ct_analysis / ctv_segmentation (core)")
        print("  3-8:   hallucination / dose / context / safety / error_recovery")
        print("  9-10:  knowledge_tools / web_search")
        print("  11-16: hallucination / language / context / response / safety / error (refresh)")
        print("  17-20: advanced_workflows / edge_cases / regression / clinical_scenarios")
        print("  21-22: input_variations (paraphrase sets)")
        print("  23-27: planning_pipeline / ref_direction / oar_constraints / skill_selection / tool_availability")
        print("  99:    smoke (fast PR-feedback subset)")
        sys.exit(1)

    agent_id = int(sys.argv[1])
    cat_numbers = [int(x) for x in sys.argv[2:]]

    baseline_path = os.path.join(BENCHMARK_DIR, "baseline.json")
    baseline = _load_baseline(baseline_path)

    print(f"🚀 Starting Aligned Benchmark Agent {agent_id}")
    print(f"Categories: {cat_numbers}")
    print(f"Screenshots: {SCREENSHOT_DIR}")
    print(f"Reports: {REPORT_DIR}")
    print(f"Benchmark: {BENCHMARK_DIR}")

    all_results = []
    per_cat_stats = []
    for cat_num in cat_numbers:
        results = run_category(cat_num, agent_id)
        all_results.extend(results)
        if results:
            stats = {
                "n": len(results),
                "passed": sum(1 for r in results if r['passed']),
                "pass_rate": (sum(1 for r in results if r['passed']) / len(results)),
                "avg_score": sum(r['total_score'] for r in results) / len(results),
            }
            per_cat_stats.append((cat_num, stats))
            _print_baseline_diff(cat_num, stats, baseline)
            _save_baseline(baseline_path, baseline, agent_id, cat_num, results)

    # Generate summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r['passed'])
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0
    avg_score = sum(r['total_score'] for r in all_results) / total if total > 0 else 0

    print(f"\n{'='*60}")
    print(f"📊 SUMMARY - Agent {agent_id}")
    print(f"{'='*60}")
    print(f"Total Tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass Rate: {pass_rate:.1f}%")
    print(f"Avg Score: {avg_score:.3f}")
    print(f"{'='*60}")

    # Per-category summary
    if per_cat_stats:
        print("\nPer-category:")
        print("| Cat | n | Pass Rate | Avg Score |")
        print("|-----|---|-----------|-----------|")
        for cat_num, s in per_cat_stats:
            cat_name = _category_name(cat_num)
            print(f"| {cat_num:>3} ({cat_name[:20]:<20}) | {s['n']:>3} | {s['pass_rate']:>8.1%} | {s['avg_score']:>7.3f} |")

if __name__ == '__main__':
    main()
