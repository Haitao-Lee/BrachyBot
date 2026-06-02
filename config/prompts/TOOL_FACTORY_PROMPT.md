# BrachyPlan Tool Factory - Prompt Reference

> AI-BrachyAgent system prompt for LLM-driven brachytherapy planning.
> Each tool can be called independently or combined in a planning pipeline.

---

## Tool Categories

| Category | Directory | Description |
|----------|-----------|-------------|
| CTV Segmentation | `tool_factory/CTV_seg/` | Tumor/Clinical Target Volume segmentation |
| OAR Segmentation | `tool_factory/OAR_seg/` | Organs At Risk segmentation |
| Trajectory Planning | `tool_factory/traj_plan/` | Needle insertion trajectory generation |
| Seed Planning | `tool_factory/seed__plan/` | Seed placement optimization |
| Dose Engine | `tool_factory/dose_engine/` | Fast dose calculation (CNN/Gaussian) |
| Dose Evaluation | `tool_factory/dose_eval/` | Dose metrics (Vx/Dx/DVH) |
| Seed Segmentation | `tool_factory/seed_seg/` | Intra-operative seed detection |
| Image Processing | `tool_factory/image_processing/` | Image loading and preprocessing |
| Plan Quality | `tool_factory/plan_quality/` | Plan scoring, constraint checking, refinement |
| Output | `tool_factory/output/` | Dose export, DICOM RT, report generation |

---

## Quick Start

```python
from tool_factory.<category> import get_tool, list_tools

# List all available tools in a category
print(list_tools())

# Get a specific tool
tool = get_tool("tool_name")

# Execute with parameters
result = tool.execute(image=ct_image, target_value=1)
```

---

## CTV Segmentation Tools (`tool_factory/CTV_seg/`)

### Tumor-specific segmentation tools:

---

### 1. Pancreatic Tumor Segmentation

**File:** `tool_factory/CTV_seg/pancreatic_tumor.py`

**Tool Name:** `pancreatic_tumor_segmentation`

**Description:**
Segment pancreatic tumors from CT images using nnU-Net deep learning model. Returns a binary mask where 1 indicates tumor tissue. Falls back to threshold-based segmentation if model is unavailable.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image` | SimpleITK Image | No* | - | CT scan image |
| `image_path` | string | No* | - | Path to CT file (.nii, .nii.gz, .mhd) |
| `target_value` | number | No | 1 | Value for tumor voxels |
| `fast_mode` | boolean | No | False | Disable TTA, reduce threads |

*Either `image` or `image_path` is required.

**Output:**
```python
{
    "ctv_mask": SimpleITK.Image,    # Binary tumor mask
    "ctv_array": numpy.ndarray,     # Tumor mask array
    "ctv_volume_mm3": float,        # Tumor volume in mm³
    "ctv_voxel_count": int,          # Number of tumor voxels
    "method": "nnunet" | "threshold_fallback"
}
```

**How to Call:**
```python
from tool_factory.CTV_seg import get_tool

tool = get_tool("pancreatic_tumor")
result = tool.execute(image=ct_image, target_value=1)
ctv_mask = result.data
```

---

### 2. Liver Tumor Segmentation

**File:** `tool_factory/CTV_seg/liver_tumor.py`

**Tool Name:** `liver_tumor_segmentation`

**Description:**
Segment liver tumors using TotalSegmentator liver_vessels task. Extracts tumor label (label 2) from the segmentation output.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image` | SimpleITK Image | No* | - | CT scan image |
| `image_path` | string | No* | - | Path to CT file |
| `target_value` | number | No | 1 | Value for tumor voxels |
| `fast_mode` | boolean | No | False | Use fast mode |

**Output:**
```python
{
    "ctv_mask": SimpleITK.Image,
    "ctv_array": numpy.ndarray,
    "ctv_volume_mm3": float,
    "ctv_voxel_count": int,
    "method": "totalsegmentator" | "threshold_fallback"
}
```

**How to Call:**
```python
tool = get_tool("liver_tumor")
result = tool.execute(image=ct_image)
```

---

### 3. Kidney Tumor Segmentation

**File:** `tool_factory/CTV_seg/kidney_tumor.py`

**Tool Name:** `kidney_tumor_segmentation`

**Description:**
Segment kidney tumors using TotalSegmentator kidney task.

**Input/Output:** Same structure as liver_tumor.

**How to Call:**
```python
tool = get_tool("kidney_tumor")
result = tool.execute(image=ct_image)
```

---

### 4. Prostate Tumor Segmentation

**File:** `tool_factory/CTV_seg/prostate_tumor.py`

**Tool Name:** `prostate_tumor_segmentation`

**Description:**
Segment prostate tumors using TotalSegmentator prostate task.

**Input/Output:** Same structure as liver_tumor.

**How to Call:**
```python
tool = get_tool("prostate_tumor")
result = tool.execute(image=ct_image)
```

---

### 5. Lung Tumor Segmentation

**File:** `tool_factory/CTV_seg/lung_tumor.py`

**Tool Name:** `lung_tumor_segmentation`

**Description:**
Segment lung tumors using TotalSegmentator lung_vessels task.

**Input/Output:** Same structure as liver_tumor.

**How to Call:**
```python
tool = get_tool("lung_tumor")
result = tool.execute(image=ct_image)
```

---

### 6. Head and Neck Tumor Segmentation

**File:** `tool_factory/CTV_seg/head_neck_tumor.py`

**Tool Name:** `head_neck_tumor_segmentation`

**Description:**
Segment head and neck tumors using TotalSegmentator total task.

**Input/Output:** Same structure as liver_tumor.

**How to Call:**
```python
tool = get_tool("head_neck_tumor")
result = tool.execute(image=ct_image)
```

---

## OAR Segmentation Tools (`tool_factory/OAR_seg/`)

---

### 7. TotalSegmentator OAR Segmentation

**File:** `tool_factory/OAR_seg/totalsegmentator_oar.py`

**Tool Name:** `totalsegmentator_oar`

**Description:**
Segment all Organs At Risk using TotalSegmentator 'total' task. Returns multi-label mask with 40+ anatomical structures. Dose constraints can be provided per organ.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image` | SimpleITK Image | No* | - | CT scan image |
| `image_path` | string | No* | - | Path to CT file |
| `organ_filter` | array | No | all | List of organ names to include |
| `dose_constraints` | object | No | {} | Constraints per organ, e.g. {'liver': 30.0} in Gy |
| `fast_mode` | boolean | No | False | Use fast mode |

**Available Organs (subset):**
- body, kidney_right, kidney_left, liver, pancreas, spleen, stomach
- adrenal_gland_right, adrenal_gland_left, aorta, posterior_vena_cava
- small_bowel, urinary_bladder, femur_left, femur_right, heart, lung_left, lung_right
- prostate, thyroid_gland, rib, sternum, spinal_cord, etc.

**Output:**
```python
{
    "oar_mask": SimpleITK.Image,           # Multi-label OAR mask
    "oar_array": numpy.ndarray,            # OAR mask array
    "organ_volumes": {"organ_name": float},  # Volume in mm³
    "organ_counts": {"organ_name": int},     # Voxel counts
    "dose_constraints": dict,              # Passed-through constraints
    "method": "totalsegmentator"
}
```

**How to Call:**
```python
tool = get_tool("totalsegmentator_oar")
result = tool.execute(
    image=ct_image,
    organ_filter=['liver', 'kidney_right', 'pancreas'],
    dose_constraints={'liver': 30.0, 'kidney_right': 20.0}
)
```

---

### 8. Pancreatic OAR Segmentation

**File:** `tool_factory/OAR_seg/pancreatic_oar.py`

**Tool Name:** `pancreatic_oar`

**Description:**
Segment pancreatic surrounding OAR structures (artery, vein, pancreas) using nnU-Net. Excludes tumor (label 1) from output. Returns only OAR labels 2, 3, 4.

**Label Mapping:**

| Label | Organ | Is OAR |
|-------|-------|--------|
| 1 | pancreatic_tumor | ❌ (CTV) |
| 2 | artery | ✅ |
| 3 | vein | ✅ |
| 4 | pancreas | ✅ |
| 5, 6 | unknown | ❌ |

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image` | SimpleITK Image | No* | - | CT scan image |
| `image_path` | string | No* | - | Path to CT file |
| `dose_constraints` | object | No | {} | Constraints per organ in Gy |
| `fast_mode` | boolean | No | False | Disable TTA |

**Output:**
```python
{
    "oar_mask": SimpleITK.Image,
    "oar_array": numpy.ndarray,
    "organ_volumes": {"artery": float, "vein": float, "pancreas": float},
    "organ_counts": {"artery": int, "vein": int, "pancreas": int},
    "dose_constraints": dict,
    "method": "nnunet"
}
```

**How to Call:**
```python
tool = get_tool("pancreatic_oar")
result = tool.execute(
    image=ct_image,
    dose_constraints={'artery': 120.0, 'vein': 120.0, 'pancreas': 50.0}
)
```

---

## Trajectory Planning Tools (`tool_factory/traj_plan/`)

---

### 9. Trajectory Initialization

**File:** `tool_factory/traj_plan/trajectory_init.py`

**Tool Name:** `trajectory_init`

**Description:**
Generate candidate needle/catheter insertion trajectories using conical direction sampling around a reference direction. Each trajectory contains origin point, direction vector, and depth information.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dose_image` | SimpleITK Image | Yes | - | CT scan for geometry |
| `radiation_volume` | numpy array | Yes | - | 3D mask (1=target, 0=background, 3=OAR) |
| `ref_direc` | array[3] | No | auto | Reference direction [x, y, z] |
| `direc_resolution` | array[3] | No | [30, 3, 2] | [cone_angle, angular_step, n_rings] |
| `extract_angle` | number | No | 30 | Cone half-angle in degrees |
| `target_value` | number | No | 1 | Target label value |
| `background_value` | number | No | 0 | Background label value |
| `obstacle_value` | number | No | 3 | OAR label value |
| `maximum_candidate_trajectories` | integer | No | 500 | Max trajectories to generate |
| `min_depth` | number | No | 2 | Minimum depth in mm |

**Output:**
```python
{
    "trajectories": list,    # List of [origin, direction, depth, bg_depths]
    "num_trajectories": int,
    "reference_direction": array[3],
    "max_depth_mm": float
}
```

**How to Call:**
```python
tool = get_tool("trajectory_init")
result = tool.execute(
    dose_image=ct_image,
    radiation_volume=rad_volume,
    ref_direc=[0, 0, 1],
    maximum_candidate_trajectories=500
)
trajectories = result.data
```

---

### 10. Trajectory Refinement

**File:** `tool_factory/traj_plan/trajectory_refine.py`

**Tool Name:** `trajectory_refine`

**Description:**
Filter and refine candidate trajectories based on quality metrics: target coverage, OAR clearance, angular deviation. Returns high-quality trajectories ready for seed planning.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `trajectories` | array | Yes | - | List from trajectory_init |
| `radiation_volume` | numpy array | Yes | - | Target/OAR mask |
| `ref_direc` | array[3] | No | [0,0,1] | Reference direction |
| `target_value` | number | No | 1 | Target label |
| `obstacle_value` | number | No | 3 | OAR label |
| `min_target_coverage` | number | No | 0.8 | Min coverage ratio |
| `max_angular_deviation` | number | No | 45 | Max angle deviation (degrees) |
| `max_trajectories` | integer | No | 50 | Max trajectories to return |

**Output:**
```python
{
    "refined_trajectories": list,
    "num_trajectories": int,
    "quality_scores": list  # Score per trajectory
}
```

**How to Call:**
```python
tool = get_tool("trajectory_refine")
result = tool.execute(
    trajectories=trajectories,
    radiation_volume=rad_volume,
    ref_direc=[0, 0, 1],
    min_target_coverage=0.8
)
```

---

## Seed Planning Tools (`tool_factory/seed__plan/`)

---

### 11. Unified Seed Planning

**File:** `tool_factory/seed__plan/seed_planning.py`

**Tool Name:** `seed_planning`

**Description:**
Unified interface for seed placement optimization supporting both rule-based and RL modes. Generates optimized seed positions along trajectories with dose distribution.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `trajectories` | array | Yes | - | List from trajectory planning |
| `radiation_volume` | numpy array | Yes | - | Target/OAR mask |
| `dose_image` | SimpleITK Image | Yes | - | CT for DL inference |
| `mode` | string | No | rule_based | 'rule_based' or 'rl' |
| `dl_params` | object | No | {} | DL model parameters |
| `rf_params` | object | No | {} | RL parameters (for 'rl' mode) |
| `seed_info` | object | No | default | {radius, length, num_of_seeds, seed_avr_dose} |
| `target_value` | number | No | 1 | Target label |
| `in_lowest_dose` | number | No | 1 | Min target dose (Gy) |
| `out_highest_dose` | number | No | 1 | Max healthy tissue dose (Gy) |
| `DVH_rate` | number | No | 0.9 | Target DVH coverage |
| `infer_img_size` | array[3] | No | [32,32,32] | CNN patch size |
| `image_normalize` | array[3] | No | [-1000,3000,255] | [min, max, scale] |

**Output:**
```python
{
    "optimal_plan": list,        # [trajectory, seeds, per_seed_doses]
    "dose_distribution": numpy.ndarray,
    "total_seeds": int,
    "num_trajectories": int,
    "mode": string
}
```

**How to Call:**
```python
tool = get_tool("seed_planning")
result = tool.execute(
    trajectories=trajectories,
    radiation_volume=rad_volume,
    dose_image=ct_image,
    mode="rule_based",
    seed_info={"radius": 0.4, "length": 4.5, "seed_avr_dose": 50}
)
plan = result.data
```

---

### 12. Rule-Based Seed Planning

**File:** `tool_factory/seed__plan/seed_planning_rule_based.py`

**Tool Name:** `seed_planning_rule_based`

**Description:**
Iterative greedy seed placement with DL-based dose refinement. Optimizes seed positions based on DVH metrics and distance filtering.

**Input/Output:** Same as unified tool (mode fixed to rule_based).

**How to Call:**
```python
tool = get_tool("seed_planning_rule_based")
result = tool.execute(trajectories=..., radiation_volume=..., dose_image=...)
```

---

### 13. RL-Based Seed Planning (REINFORCE)

**File:** `tool_factory/seed__plan/seed_planning_rl.py`

**Tool Name:** `seed_planning_rl`

**Description:**
Hierarchical REINFORCE reinforcement learning for seed optimization. High-level policy selects trajectories, low-level policy optimizes seed positions. CNN surrogate for fast dose prediction.

**Input/Output:** Same as unified tool (mode fixed to rl).

**RL Parameters:**
```python
rf_params = {
    "max_episodes": 100,   # Training episodes
    "bandwidth": 0.1       # Policy bandwidth
}
```

**How to Call:**
```python
tool = get_tool("seed_planning_rl")
result = tool.execute(
    trajectories=...,
    radiation_volume=...,
    dose_image=...,
    rf_params={"max_episodes": 100, "bandwidth": 0.1}
)
```

---

## Seed Segmentation Tool (`tool_factory/seed_seg/`)

---

### 14. Seed Detection

**File:** `tool_factory/seed_seg/__init__.py`

**Tool Name:** `seed_segmentation`

**Description:**
Detect and segment implanted brachytherapy seeds from intra-operative CT/CBCT images. Uses intensity thresholding and connected component analysis.

**Input Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image` | SimpleITK Image | No* | - | Intra-op CT/CBCT |
| `image_path` | string | No* | - | Path to image file |
| `seed_threshold` | number | No | 2000 | HU threshold for seeds |
| `min_seed_volume` | number | No | 3 | Min connected component (voxels) |
| `max_seed_volume` | number | No | 200 | Max connected component (voxels) |
| `gaussian_sigma` | number | No | 0.5 | Gaussian smoothing sigma |
| `planned_seeds` | array | No | - | Planned positions for deviation analysis |

**Output:**
```python
{
    "detected_seeds": [
        {
            "id": int,
            "voxel_position": [x, y, z],
            "physical_position": [x, y, z],
            "volume_voxels": int
        },
        ...
    ],
    "seed_mask": numpy.ndarray,
    "num_detected": int,
    "deviation_stats": {
        "mean_deviation_mm": float,
        "max_deviation_mm": float,
        "individual_deviations_mm": list
    }
}
```

**How to Call:**
```python
tool = get_tool("seed_segmentation")
result = tool.execute(
    image=cbct_image,
    seed_threshold=2000,
    planned_seeds=planned_positions
)
```

---

## Dose Evaluation Tools (`tool_factory/dose_eval/`)

*(To be implemented)*

---

## Tool Execution Pattern

```python
from tool_factory.<category> import get_tool

# Step 1: Get the tool
tool = get_tool("tool_name")

# Step 2: Execute with parameters
result = tool.execute(
    image=ct_image,           # or image_path
    target_value=1,
    fast_mode=False,
    # ... other parameters
)

# Step 3: Check result
if result.success:
    data = result.data           # Primary output
    metadata = result.metadata   # Additional info
    message = result.message     # Human-readable message
else:
    error = result.error        # Error message

# Step 4: Use the output
ctv_mask = metadata["ctv_mask"]
```

---

## Pipeline Example: Complete Brachytherapy Planning

```python
from tool_factory.CTV_seg import get_tool as get_ctv_tool
from tool_factory.OAR_seg import get_tool as get_oar_tool
from tool_factory.traj_plan import get_tool as get_traj_tool
from tool_factory.seed__plan import get_tool as get_seed_tool

# 1. Segment CTV (pancreatic tumor)
ctv_tool = get_ctv_tool("pancreatic_tumor")
ctv_result = ctv_tool.execute(image=ct_image, target_value=1)
ctv_mask = ctv_result.data

# 2. Segment OAR (pancreatic surrounding)
oar_tool = get_oar_tool("pancreatic_oar")
oar_result = oar_tool.execute(image=ct_image)
oar_mask = oar_result.data

# 3. Combine into radiation volume
rad_volume = np.zeros_like(ctv_array)
rad_volume[ctv_array == 1] = 1      # Target
rad_volume[oar_array > 1] = 3       # OAR

# 4. Generate trajectories
traj_tool = get_traj_tool("trajectory_init")
traj_result = traj_tool.execute(
    dose_image=ct_image,
    radiation_volume=rad_volume
)
trajectories = traj_result.data

# 5. Optimize seed placement
seed_tool = get_seed_tool("seed_planning")
plan_result = seed_tool.execute(
    trajectories=trajectories,
    radiation_volume=rad_volume,
    dose_image=ct_image,
    mode="rl"
)
optimal_plan = plan_result.data
dose_distribution = plan_result.metadata["dose_distribution"]

# 6. Evaluate dose
metrics = compute_dvh_metrics(dose_distribution, ctv_array, oar_array)
```

---

## Error Handling

All tools return a `ToolResult` with:
- `success`: Boolean indicating success/failure
- `data`: Primary output (varies by tool)
- `message`: Human-readable status message
- `metadata`: Additional information dictionary
- `error`: Error message if failed

```python
result = tool.execute(**params)
if not result.success:
    print(f"Error: {result.error}")
    print(f"Message: {result.message}")
else:
    print(result.message)  # e.g., "Segmentation completed. Found 1234 tumor voxels."
```

---

## Notes

- All images should be SimpleITK Image objects or file paths
- Radiation volume uses label encoding: 1=target, 0=background, 3=OAR (configurable)
- Coordinate systems: RAS for physical coordinates, IJK for voxel indices
- Dose values are in Gy units (pre-scaled)
- nnU-Net models require pre-trained weights in `plans/seg/<model_name>/`
- TotalSegmentator requires CLI installation and must be in PATH

---

*Document Version: 1.0*
*Generated: 2026-05-14*
