#!/bin/bash
# Run 4 aligned benchmark agents in parallel
# Each agent handles different categories

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="/home/lht/snap/brachyplan/BrachyBot"
SCREENSHOT_DIR="$BASE_DIR/docs/benchmark_result/screenshots"
REPORT_DIR="$BASE_DIR/docs/benchmark_result/reports"

# Create directories
mkdir -p "$SCREENSHOT_DIR"
mkdir -p "$REPORT_DIR"

# Clean old results
echo "Cleaning old results..."
rm -f "$SCREENSHOT_DIR"/*.png
rm -f "$REPORT_DIR"/agent*.md

# Function to run agent
run_agent() {
    local agent_id=$1
    shift
    local categories=("$@")

    echo "Starting Agent $agent_id with categories: ${categories[*]}"
    cd "$SCRIPT_DIR"
    python3 aligned_benchmark.py $agent_id "${categories[@]}"
}

# Agent 1: Categories 1-8, 17 (Basic + Safety)
run_agent 1 1 2 3 4 5 6 8 17 &
AGENT1_PID=$!

# Agent 2: Categories 10-14 (Advanced + Adversarial)
run_agent 2 10 11 12 13 14 &
AGENT2_PID=$!

# Agent 3: Categories 19-27 (Workflow + Compliance)
run_agent 3 19 20 21 22 23 24 25 26 27 &
AGENT3_PID=$!

# Agent 4: Categories 7, 9, 15, 18 (UI + Edge Cases)
run_agent 4 7 9 15 18 &
AGENT4_PID=$!

echo "All agents started!"
echo "Agent 1 PID: $AGENT1_PID"
echo "Agent 2 PID: $AGENT2_PID"
echo "Agent 3 PID: $AGENT3_PID"
echo "Agent 4 PID: $AGENT4_PID"

# Wait for all agents to complete
wait $AGENT1_PID
echo "Agent 1 completed"

wait $AGENT2_PID
echo "Agent 2 completed"

wait $AGENT3_PID
echo "Agent 3 completed"

wait $AGENT4_PID
echo "Agent 4 completed"

echo "All agents completed!"

# Generate final report
echo "Generating final report..."
cd "$SCRIPT_DIR"
python3 generate_final_report.py
