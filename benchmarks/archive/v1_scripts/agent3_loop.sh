#!/bin/bash
# Auto-restart wrapper for agent3 runner
cd /home/lht/snap/brachyplan/BrachyBot
echo "Starting Agent 3 loop at $(date)"

while true; do
    echo "=== Starting runner at $(date) ==="
    python3 benchmarks/agent3_cat_runner.py 19 20 21 22 23
    EXIT_CODE=$?
    echo "=== Runner exited with code $EXIT_CODE at $(date) ==="
    
    # Wait for server to recover before restarting
    echo "Waiting 30s before restart..."
    sleep 30
    
    # Wait for server
    for i in $(seq 1 20); do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ --max-time 5 2>/dev/null | grep -q 200; then
            echo "Server is back!"
            break
        fi
        echo "Waiting for server... ($i/20)"
        sleep 10
    done
done
