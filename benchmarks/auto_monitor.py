#!/usr/bin/env python3
"""
Auto Monitor and Restart Benchmark Agents
- Monitors agent progress
- Restarts stuck or non-compliant agents
- No permission required - autonomous operation
"""
import os, sys, time, subprocess, signal, json, glob, re
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
SCREENSHOT_DIR = os.path.join(_ROOT, "docs", "benchmark_result", "screenshots_v2")
REPORT_DIR = os.path.join(_ROOT, "docs", "benchmark_result", "reports_v2")
BENCHMARK_DIR = os.path.join(_ROOT, "benchmarks", "v2")
LOG_FILE = os.path.join(_ROOT, "docs", "benchmark_result", "auto_monitor_v2.log")

# Agent configuration (v2: 8 categories)
AGENTS = {
    1: [1, 2, 3],
    2: [4, 5],
    3: [6, 7],
    4: [8]
}

def log_message(message, level="INFO"):
    """Log message to file and print."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line, flush=True)

    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception:
        pass

def get_screenshot_count():
    """Count total screenshots."""
    try:
        return len(glob.glob(f"{SCREENSHOT_DIR}/*.png"))
    except Exception:
        return 0

def get_agent_processes():
    """Get all running agent processes."""
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        processes = {}
        for line in result.stdout.split('\n'):
            if 'aligned_benchmark.py' in line and 'grep' not in line:
                parts = line.split()
                if len(parts) >= 11:
                    pid = parts[1]
                    # Extract agent ID from command
                    for arg in parts[10:]:
                        if arg.isdigit() and int(arg) in AGENTS:
                            agent_id = int(arg)
                            processes[agent_id] = pid
        return processes
    except Exception:
        return {}

def check_agent_progress(agent_id, last_check_time, last_screenshot_count):
    """Check if agent is making progress."""
    current_screenshots = get_screenshot_count()
    current_time = time.time()

    # Calculate time elapsed
    time_elapsed = current_time - last_check_time

    # Calculate screenshots taken since last check
    screenshots_taken = current_screenshots - last_screenshot_count

    # If no progress for 10 minutes, agent might be stuck
    if time_elapsed > 600 and screenshots_taken == 0:
        return False, "No progress for 10 minutes"

    # If very slow progress (less than 1 screenshot per 2 minutes)
    if time_elapsed > 120 and screenshots_taken < 1:
        return False, "Very slow progress"

    return True, "Making progress"

def check_compliance(agent_id):
    """Check if agent is following rules."""
    # Check for language consistency issues in recent reports
    report_files = glob.glob(f"{REPORT_DIR}/agent{agent_id}_*.md")

    for report_file in report_files:
        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check for language mismatch patterns
            language_mismatch_count = len(re.findall(r'language_mismatch', content))
            if language_mismatch_count > 5:
                return False, f"Too many language mismatch issues: {language_mismatch_count}"

            # Check for safety leaks
            safety_leak_count = len(re.findall(r'safety_leak', content))
            if safety_leak_count > 0:
                return False, f"Safety leak detected: {safety_leak_count}"

        except Exception:
            pass

    return True, "Compliant"

def stop_agent(agent_id):
    """Stop a specific agent."""
    try:
        # Find the process
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if f'aligned_benchmark.py {agent_id}' in line and 'grep' not in line:
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    log_message(f"Stopping agent {agent_id} (PID: {pid})")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(2)
                    # Force kill if still running
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
                    return True
    except Exception as e:
        log_message(f"Error stopping agent {agent_id}: {e}")
    return False

def start_agent(agent_id, categories):
    """Start a specific agent."""
    try:
        log_message(f"Starting agent {agent_id} with categories: {categories}")

        # Start the agent in background
        cmd = f"cd {BENCHMARK_DIR} && python3 aligned_benchmark.py {agent_id} {' '.join(map(str, categories))}"
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=BENCHMARK_DIR
        )

        log_message(f"Agent {agent_id} started with PID: {process.pid}")
        return True
    except Exception as e:
        log_message(f"Error starting agent {agent_id}: {e}")
        return False

def restart_agent(agent_id, categories):
    """Restart a specific agent."""
    log_message(f"Restarting agent {agent_id}")

    # Stop the agent
    stop_agent(agent_id)
    time.sleep(5)

    # Start the agent
    return start_agent(agent_id, categories)

def monitor_and_restart():
    """Main monitoring loop."""
    log_message("="*60)
    log_message("Starting Auto Monitor and Restart System")
    log_message("="*60)

    # Track state for each agent
    agent_state = {}
    for agent_id in AGENTS:
        agent_state[agent_id] = {
            'last_check_time': time.time(),
            'last_screenshot_count': 0,
            'restart_count': 0,
            'last_restart_time': None
        }

    while True:
        try:
            log_message("\n--- Monitoring Cycle ---")

            # Get current state
            current_screenshots = get_screenshot_count()
            running_processes = get_agent_processes()

            log_message(f"Total screenshots: {current_screenshots}")
            log_message(f"Running agents: {list(running_processes.keys())}")

            # Check each agent
            for agent_id, categories in AGENTS.items():
                log_message(f"\nChecking Agent {agent_id}:")

                # Check if agent is running
                if agent_id not in running_processes:
                    log_message(f"  Agent {agent_id} is NOT running")

                    # Check if it has completed its work
                    completed_categories = set()
                    for cat in categories:
                        cat_files = glob.glob(f"{REPORT_DIR}/agent{agent_id}_*_*.md")
                        if cat_files:
                            completed_categories.add(cat)

                    if len(completed_categories) >= len(categories):
                        log_message(f"  Agent {agent_id} has completed all categories")
                    else:
                        log_message(f"  Agent {agent_id} needs restart")
                        if restart_agent(agent_id, categories):
                            agent_state[agent_id]['restart_count'] += 1
                            agent_state[agent_id]['last_restart_time'] = time.time()
                            log_message(f"  Agent {agent_id} restarted successfully")
                        else:
                            log_message(f"  Failed to restart agent {agent_id}")
                else:
                    log_message(f"  Agent {agent_id} is running (PID: {running_processes[agent_id]})")

                    # Check progress
                    progress_ok, progress_msg = check_agent_progress(
                        agent_id,
                        agent_state[agent_id]['last_check_time'],
                        agent_state[agent_id]['last_screenshot_count']
                    )

                    if not progress_ok:
                        log_message(f"  Agent {agent_id} progress issue: {progress_msg}")

                        # Restart immediately
                        if restart_agent(agent_id, categories):
                            agent_state[agent_id]['restart_count'] += 1
                            agent_state[agent_id]['last_restart_time'] = time.time()
                            log_message(f"  Agent {agent_id} restarted due to progress issue")
                        else:
                            log_message(f"  Failed to restart agent {agent_id}")
                    else:
                        log_message(f"  Agent {agent_id} progress: {progress_msg}")

                    # Check compliance
                    compliance_ok, compliance_msg = check_compliance(agent_id)
                    if not compliance_ok:
                        log_message(f"  Agent {agent_id} compliance issue: {compliance_msg}")

                        # Restart immediately
                        if restart_agent(agent_id, categories):
                            agent_state[agent_id]['restart_count'] += 1
                            agent_state[agent_id]['last_restart_time'] = time.time()
                            log_message(f"  Agent {agent_id} restarted due to compliance issue")
                        else:
                            log_message(f"  Failed to restart agent {agent_id}")

                    # Update state
                    agent_state[agent_id]['last_check_time'] = time.time()
                    agent_state[agent_id]['last_screenshot_count'] = current_screenshots

            # Check if all agents have completed
            all_completed = True
            for agent_id, categories in AGENTS.items():
                if agent_id not in running_processes:
                    # Check if all categories are completed
                    completed_count = 0
                    for cat in categories:
                        cat_files = glob.glob(f"{REPORT_DIR}/agent{agent_id}_*_*.md")
                        if cat_files:
                            completed_count += 1
                    if completed_count < len(categories):
                        all_completed = False
                        break
                else:
                    all_completed = False
                    break

            if all_completed:
                log_message("\n" + "="*60)
                log_message("ALL AGENTS HAVE COMPLETED THEIR WORK")
                log_message("="*60)
                break

            # Wait before next check
            log_message("\nWaiting 5 minutes before next check...")
            time.sleep(300)

        except KeyboardInterrupt:
            log_message("\nMonitoring stopped by user")
            break
        except Exception as e:
            log_message(f"Error in monitoring loop: {e}")
            time.sleep(60)

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Start monitoring
    monitor_and_restart()
