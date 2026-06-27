#!/usr/bin/env python3
"""Quick test: send planning request and check if _store_tool_result is called."""
import time, json, requests

BASE = "http://127.0.0.1:5000"

# Send planning request via SSE
print("Sending planning request...")
resp = requests.post(f"{BASE}/api/chat", json={
    "message": "Perform brachytherapy planning for a pancreatic tumor patient",
    "stream": True,
}, stream=True, timeout=300)

# Read SSE events
events = []
for line in resp.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        try:
            data = json.loads(line[6:])
            events.append(data)
            if data.get("type") == "step":
                tool = data.get("tool", "")
                status = data.get("status", "")
                if tool:
                    print(f"  Step: {tool} [{status}]")
        except:
            pass
    if len(events) > 100:
        break

print(f"\nTotal events: {len(events)}")

# Check planning results
try:
    r = requests.get(f"{BASE}/api/planning/results", timeout=5)
    d = r.json()
    print(f"Planning results: has_dose={d.get('has_dose')}, seeds={d.get('total_seeds')}, metrics={list(d.get('metrics',{}).keys())[:5]}")
except Exception as e:
    print(f"Error checking results: {e}")
