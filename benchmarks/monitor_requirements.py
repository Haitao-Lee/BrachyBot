#!/usr/bin/env python3
"""
Monitor benchmark requirements compliance.
Checks all requirements are being enforced during testing.
"""
import os, glob, re, json, time
from datetime import datetime

SCREENSHOT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/screenshots"
REPORT_DIR = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports"
LOG_FILE = "/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/benchmark_run.log"

def check_screenshot_response_alignment():
    """Check that screenshots match recorded responses."""
    print("\n=== Checking Screenshot-Response Alignment ===")

    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")
    issues = []

    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all screenshot references
        screenshots = re.findall(r'!\[.*?\]\(\.\./screenshots/(.*?)\)', content)

        for screenshot_name in screenshots:
            screenshot_path = f"{SCREENSHOT_DIR}/{screenshot_name}"
            if not os.path.exists(screenshot_path):
                issues.append(f"Missing screenshot: {screenshot_name}")

            # Check screenshot size
            elif os.path.getsize(screenshot_path) < 1000:
                issues.append(f"Small screenshot: {screenshot_name} ({os.path.getsize(screenshot_path)} bytes)")

    if issues:
        print(f"❌ Found {len(issues)} alignment issues:")
        for issue in issues[:10]:  # Show first 10
            print(f"  - {issue}")
    else:
        print("✅ All screenshots aligned with responses")

    return len(issues)

def check_language_consistency():
    """Check language consistency in reports."""
    print("\n=== Checking Language Consistency ===")

    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")
    issues = []

    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all input-response pairs
        inputs = re.findall(r'\*\*Input:\*\*\s*(.*?)(?=\n\n|\*\*)', content, re.DOTALL)
        responses = re.findall(r'\*\*Response:\*\*\s*>\s*(.*?)(?=\n\n|\*\*)', content, re.DOTALL)

        for i, (input_text, response_text) in enumerate(zip(inputs, responses)):
            # Simple language detection
            chinese_in = len(re.findall(r'[一-鿿]', input_text))
            english_in = len(re.findall(r'[a-zA-Z]', input_text))
            chinese_resp = len(re.findall(r'[一-鿿]', response_text))
            english_resp = len(re.findall(r'[a-zA-Z]', response_text))

            input_lang = 'zh' if chinese_in > english_in * 0.3 else 'en'
            response_lang = 'zh' if chinese_resp > english_resp * 0.3 else 'en'

            if input_lang == 'zh' and response_lang == 'en':
                issues.append(f"Language mismatch in {os.path.basename(report_file)}: Chinese input → English response")
            elif input_lang == 'en' and response_lang == 'zh':
                if chinese_resp / len(response_text) > 0.3:
                    issues.append(f"Language mismatch in {os.path.basename(report_file)}: English input → Chinese response")

    if issues:
        print(f"❌ Found {len(issues)} language consistency issues:")
        for issue in issues[:10]:
            print(f"  - {issue}")
    else:
        print("✅ All responses have consistent language")

    return len(issues)

def check_hallucination_detection():
    """Check hallucination detection in reports."""
    print("\n=== Checking Hallucination Detection ===")

    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")
    issues = []

    hallucination_phrases = ["I don't know", "I'm not sure", "I cannot verify", "I'm just guessing"]

    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all responses
        responses = re.findall(r'\*\*Response:\*\*\s*>\s*(.*?)(?=\n\n|\*\*)', content, re.DOTALL)

        for response in responses:
            for phrase in hallucination_phrases:
                if phrase.lower() in response.lower():
                    issues.append(f"Hallucination phrase found in {os.path.basename(report_file)}: {phrase}")

    if issues:
        print(f"❌ Found {len(issues)} hallucination issues:")
        for issue in issues[:10]:
            print(f"  - {issue}")
    else:
        print("✅ No hallucination phrases detected")

    return len(issues)

def check_safety_validation():
    """Check safety validation in reports."""
    print("\n=== Checking Safety Validation ===")

    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")
    issues = []

    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all responses
        responses = re.findall(r'\*\*Response:\*\*\s*>\s*(.*?)(?=\n\n|\*\*)', content, re.DOTALL)

        for response in responses:
            # Check for common safety issues (simplified)
            safety_phrases = ["dangerous", "harmful", "toxic", "lethal"]
            for phrase in safety_phrases:
                if phrase.lower() in response.lower():
                    issues.append(f"Potential safety issue in {os.path.basename(report_file)}: {phrase}")

    if issues:
        print(f"❌ Found {len(issues)} safety issues:")
        for issue in issues[:10]:
            print(f"  - {issue}")
    else:
        print("✅ No safety issues detected")

    return len(issues)

def check_response_length():
    """Check response length compliance."""
    print("\n=== Checking Response Length ===")

    report_files = glob.glob(f"{REPORT_DIR}/agent*_*.md")
    issues = []

    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all responses
        responses = re.findall(r'\*\*Response:\*\*\s*>\s*(.*?)(?=\n\n|\*\*)', content, re.DOTALL)

        for response in responses:
            if len(response) < 100:
                issues.append(f"Too brief response in {os.path.basename(report_file)}: {len(response)} chars")
            elif len(response) > 5000:
                issues.append(f"Too verbose response in {os.path.basename(report_file)}: {len(response)} chars")

    if issues:
        print(f"❌ Found {len(issues)} response length issues:")
        for issue in issues[:10]:
            print(f"  - {issue}")
    else:
        print("✅ All responses have appropriate length")

    return len(issues)

def generate_compliance_report():
    """Generate compliance report."""
    print("\n" + "="*60)
    print("BENCHMARK REQUIREMENTS COMPLIANCE REPORT")
    print("="*60)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    total_issues = 0
    total_issues += check_screenshot_response_alignment()
    total_issues += check_language_consistency()
    total_issues += check_hallucination_detection()
    total_issues += check_safety_validation()
    total_issues += check_response_length()

    print("\n" + "="*60)
    if total_issues == 0:
        print("✅ ALL REQUIREMENTS COMPLIANT")
    else:
        print(f"❌ FOUND {total_issues} COMPLIANCE ISSUES")
    print("="*60)

    return total_issues

if __name__ == '__main__':
    while True:
        try:
            generate_compliance_report()
            print("\nWaiting 5 minutes for next check...")
            time.sleep(300)  # Check every 5 minutes
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
            break
        except Exception as e:
            print(f"\nError during monitoring: {e}")
            time.sleep(60)
