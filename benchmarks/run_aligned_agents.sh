#!/bin/bash
# Run 4 aligned benchmark agents in parallel (v2)
# Each agent handles different categories

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="/home/lht/snap/brachyplan/BrachyBot"
SCREENSHOT_DIR="$BASE_DIR/docs/benchmark_result/screenshots_v2"
REPORT_DIR="$BASE_DIR/docs/benchmark_result/reports_v2"

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

# Agent 1: Categories 1-3 (tool_calling, multi_step, hallucination)
run_agent 1 1 2 3 &
AGENT1_PID=$!

# Agent 2: Categories 4-5 (language, context)
run_agent 2 4 5 &
AGENT2_PID=$!

# Agent 3: Categories 6-7 (response_quality, safety)
run_agent 3 6 7 &
AGENT3_PID=$!

# Agent 4: Category 8 (error_recovery)
run_agent 4 8 &
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
