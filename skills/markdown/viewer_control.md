---
name: viewer_control
description: Control the CT viewer (window/level, slice navigation, overlays)
category: viewer
triggers:
  - viewer
  - window
  - slice
  - overlay
tool_sequence:
  - code_executor
parameters:
  action: null
  preset: null
  window: null
  level: null
  axis: null
  slice_index: null
  overlay: null
  threshold: null
success_threshold: 1.0
version: "1.0.0"
---

# Viewer Control

Control the CT viewer through API calls.

## Available Actions

### Window/Level
- `set_preset`: Apply preset (soft, bone, lung, brain)
- `set_window`: Set custom window/level values

### Navigation
- `navigate_slice`: Go to specific slice on any axis
- `set_threshold`: Set HU threshold overlay

### Overlays
- `toggle_overlay`: Toggle CTV/OAR overlay visibility

### State
- `get_state`: Get current viewer state

## Usage

Use `code_executor` to call the viewer control API:

```python
import requests
res = requests.post('http://localhost:8080/api/viewer/control', json={
    "action": "set_preset",
    "preset": "lung"
})
print(res.json())
```

## Presets

- **soft**: W:400, L:40 (soft tissue)
- **bone**: W:2000, L:400 (bone window)
- **lung**: W:1500, L:-600 (lung window)
- **brain**: W:80, L:40 (brain window)
