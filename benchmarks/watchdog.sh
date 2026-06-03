#!/bin/bash
# Watchdog for agent4 benchmark run
AGENT4_PID=""
for i in $(seq 1 200); do
    sleep 30
    
    # Check if our agent4 scheduler is still running
    if [ -n "$AGENT4_PID" ] && ! kill -0 $AGENT4_PID 2>/dev/null; then
        echo "$(date): Agent4 scheduler (PID $AGENT4_PID) has finished"
        break
    fi
    
    # Kill competing schedulers (not our agent4)
    for pid in $(ps aux | grep "python.*robust_scheduler" | grep -v grep | grep -v "4 23 19 22 21 18 09 15 07" | awk '{print $2}'); do
        kill $pid 2>/dev/null
        echo "$(date): Killed competing scheduler PID $pid"
    done
    
    # Check server
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ --connect-timeout 5 2>/dev/null)
    if [ "$HTTP_CODE" != "200" ]; then
        echo "$(date): Server offline, restarting..."
        cd /home/lht/snap/brachyplan/BrachyBot
        pkill -f "python web/server.py" 2>/dev/null
        sleep 2
        nohup python web/server.py > /dev/null 2>&1 &
        sleep 5
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ --connect-timeout 5 2>/dev/null)
        echo "$(date): Server restart result: $HTTP_CODE"
    fi
done
echo "$(date): Watchdog exiting"
