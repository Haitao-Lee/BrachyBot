# BrachyBot Benchmark v2

## Test Material
- **CT File**: `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`
- **Patient**: 胰腺癌 (pancreatic cancer)
- **Specs**: 48 × 512 × 512 voxels, 0.68 × 0.68 × 5.0 mm spacing

## How to Run

### Step 1: Upload CT
Before running any test, the agent MUST upload the CT file to BrachyBot:
```
POST /api/chat
{
  "message": "请加载CT文件 /home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii",
  "ui_state": {"ct_path": "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"}
}
```

### Step 2: Run Tests
Each test case has a `context` field describing what must be set up BEFORE asking the question.
The testing agent must:
1. Read the `context` field
2. Set up the required state (upload CT, run segmentation, etc.)
3. Then send the `input` message
4. Verify the response matches `expected_tools`, `expected_keywords`, `forbidden_keywords`

### Context Setup Guide
| Context | Setup Action |
|---------|-------------|
| `CT已加载` | Upload CT file (Step 1) |
| `CT已加载，已执行CTV分割` | Upload CT + run CTV segmentation |
| `CT已加载，已执行OAR分割` | Upload CT + run OAR segmentation |
| `CT已加载，已完成分割和计划` | Upload CT + run segmentation + run seed planning |
| `CT已加载，未执行分割` | Upload CT only (no segmentation) |

## Categories (8, 129 cases)
1. `01_tool_calling` (26) — correct tool selection
2. `02_multi_step` (6) — all steps in order
3. `03_hallucination` (12) — no fabrication
4. `04_language` (15) — language consistency
5. `05_context` (13) — multi-turn context
6. `06_response_quality` (9) — structured output
7. `07_safety` (8) — refuse unsafe requests
8. `08_error_recovery` (10) — graceful error handling
