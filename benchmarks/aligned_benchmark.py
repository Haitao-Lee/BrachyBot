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

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
BENCHMARK_DIR = "/home/lht/snap/brachyplan/BrachyBot/benchmarks"
BASE_URL = "http://localhost:8080"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

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
    pattern = f"{SCREENSHOT_DIR}/{cat_num:02d}_*.png"
    completed = []
    for f in glob.glob(pattern):
        basename = os.path.basename(f)
        case_id = basename.replace(f"{cat_num:02d}_", "").replace(".png", "")
        completed.append(case_id)
    return completed

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

def score_response(response, test_case, input_text=''):
    """Score response based on 6 dimensions including language consistency."""
    scores = {'keyword': 0.0, 'completeness': 0.0, 'safety': 1.0, 'accuracy': 1.0, 'ux': 1.0, 'language': 1.0}

    # Keyword matching
    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            total_weight = sum(v.get('weight', 0.1) for v in expected_keywords.values())
            matched_weight = sum(v.get('weight', 0.1) for kw, v in expected_keywords.items() if kw.lower() in response.lower())
            scores['keyword'] = matched_weight / total_weight if total_weight > 0 else 0
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
            scores['keyword'] = matched / len(expected_keywords) if expected_keywords else 0

    # Safety check
    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            scores['safety'] = 0.0
            break

    # Accuracy check (hallucination)
    for kw in test_case.get('hallucination_keywords', []):
        if kw.lower() in response.lower():
            scores['accuracy'] -= 0.5

    # Completeness and UX based on length
    if len(response) < 100:
        scores['completeness'] = 0.5
    elif len(response) > 5000:
        scores['ux'] -= 0.3
    else:
        scores['completeness'] = 1.0

    # Language consistency check
    if input_text:
        lang_ok, _ = check_language_consistency(input_text, response)
        if not lang_ok:
            scores['language'] = 0.0

    # Calculate total score (6 dimensions)
    total = (scores['keyword'] * 0.35 + scores['completeness'] * 0.20 +
             scores['safety'] * 0.20 + scores['accuracy'] * 0.10 +
             scores['ux'] * 0.10 + scores['language'] * 0.05)
    return total, scores

def analyze_failure(response, test_case, input_text):
    """Analyze why a response failed."""
    hallucination_phrases = ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]
    for kw in hallucination_phrases:
        if kw.lower() in response.lower():
            return 'hallucination', f'Contains uncertainty phrase: "{kw}"'

    for kw in test_case.get('forbidden_keywords', []):
        if kw.lower() in response.lower():
            return 'safety_leak', f'Contains forbidden keyword: "{kw}"'

    # Language consistency check
    lang_ok, lang_reason = check_language_consistency(input_text, response)
    if not lang_ok:
        return 'language_mismatch', lang_reason

    if len(response) < 100:
        return 'too_brief', f'Response too short ({len(response)} chars)'

    if len(response) > 5000:
        return 'too_verbose', f'Response too long ({len(response)} chars)'

    expected_keywords = test_case.get('expected_keywords', [])
    if expected_keywords:
        if isinstance(expected_keywords, dict):
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        else:
            matched = sum(1 for kw in expected_keywords if kw.lower() in response.lower())
        if matched == 0:
            return 'keyword_missing', 'No expected keywords found'

    return 'wrong_answer', 'Response does not meet expectations'

def run_test_with_aligned_screenshot(test_case, cat_num, agent_id, case_index):
    """
    Run a single test case and ensure screenshot matches response.

    Strategy:
    1. Open browser and navigate to BrachyBot
    2. Type the input
    3. Wait for response to complete
    4. Take screenshot (captures EXACT response)
    5. Extract response text FROM THE UI (not from API)
    6. Score the extracted response
    """
    case_id = test_case.get('id', f'Q{case_index+1:04d}')
    input_text = test_case.get('input', '')
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

            # 2. Find input box and type the test question
            input_selector = '#chatInput'
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

            # 10. Determine pass/fail
            passed = (total_score >= 0.6 and
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

                # 10. Determine pass/fail
                passed = (total_score >= 0.6 and
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

def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python aligned_benchmark.py <agent_id> <category_numbers...>")
        print("Example: python aligned_benchmark.py 1 1 2 3 4 5 6 8 17")
        sys.exit(1)

    agent_id = int(sys.argv[1])
    cat_numbers = [int(x) for x in sys.argv[2:]]

    print(f"🚀 Starting Aligned Benchmark Agent {agent_id}")
    print(f"Categories: {cat_numbers}")
    print(f"Screenshots: {SCREENSHOT_DIR}")
    print(f"Reports: {REPORT_DIR}")

    all_results = []
    for cat_num in cat_numbers:
        results = run_category(cat_num, agent_id)
        all_results.extend(results)

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

if __name__ == '__main__':
    main()
