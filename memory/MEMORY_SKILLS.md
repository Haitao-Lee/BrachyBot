# BrachyBot Memory & Skills System

> Self-evolving system: Enables BrachyBot to learn through user interaction, forming planning and operation patterns that better match user habits.

---

## Overview

BrachyBot has **self-evolution capabilities** that enable it to:

1. **Remember interaction history** -- Record all conversations, tool calls, and parameter selections
2. **Learn user preferences** -- Extract commonly used parameter combinations and tool sequences from history
3. **Generate personalized skills** -- Automatically create new skills based on learned patterns
4. **Continuously optimize** -- Update preferences and skill success rates after each interaction

---

## Memory System (`memory/`)

### Interaction Memory (`interaction_memory.py`)

Records complete interaction history:

```python
from memory import InteractionMemory

memory = InteractionMemory(session_id="patient_001")

# Record conversation
memory.add_turn("user", "Generate treatment plan for pancreatic cancer patient")

# Record tool call
memory.add_tool_call(
    tool_name="ctv_segmentation",
    inputs={"tumor_type": "pancreatic"},
    outputs={"success": True},
    success=True,
    execution_time=2.3
)

# Get statistics
stats = memory.get_tool_usage_stats()
print(stats)  # {'ctv_segmentation': 5, 'seed_planning': 3, ...}

# Extract tool call patterns
patterns = memory.extract_tool_patterns(min_occurrences=3)
print(patterns)  # [['ctv_segmentation', 'oar_segmentation', 'trajectory_planning'], ...]
```

### Parameter Preference Learning (`skill_learner.py`)

Learn user habits from interaction history:

```python
from memory import SkillLearner

learner = SkillLearner(memory)

# Learn parameter preferences
prefs = learner.learn_parameter_preferences()
print(prefs)
# {
#     'seed_planning': {
#         'mode': {'value': 'rl', 'confidence': 0.8},
#     },
#     'dose_engine': {
#         'engine': {'value': 'cnn', 'confidence': 0.6},
#     }
# }

# Learn new skills from interactions
new_skills = learner.learn_from_interactions(min_occurrences=3)

# Get next recommended tool
next_tool = learner.suggest_next_tool()
print(next_tool)  # 'dose_evaluation'
```

### User Preference Store (`preference_store.py`)

Persistent storage of user preferences:

```python
from memory import PreferenceStore

store = PreferenceStore(user_id="doctor_wang")

# Set preference
store.set("planning", "default_mode", "rl", confidence=0.9, source="learned")

# Get preference
mode = store.get("planning", "default_mode")
print(mode)  # 'rl'

# Batch apply preferences to tool parameters
params = {"mode": None, "engine": None}
applied = store.apply_to_tool_params("seed_planning", params)
print(applied)  # {'mode': 'rl', 'engine': 'cnn'}
```

---

## Skills System (`skills/`)

### Skill Registration and Management (`skill_base.py`)

Skills are reusable behavioral units containing tool sequences and default parameters:

```python
from skills import SkillRegistry

registry = SkillRegistry()

# Get skill
skill = registry.get("standard_planning")
print(skill.tool_sequence)
# ['ctv_segmentation', 'oar_segmentation', 'trajectory_planning', 'seed_planning', 'dose_engine', 'dose_evaluation']

# Find by trigger word
matches = registry.find_by_trigger("pancreatic cancer treatment plan")
print(matches[0].name)  # 'standard_planning'

# Record usage result
registry.record_use("standard_planning", success=True)
```

### Preset Skills

| Skill | Trigger Words | Tool Sequence |
|-------|---------------|---------------|
| `standard_planning` | planning, standard plan, treatment plan | CTV -> OAR -> Trajectory -> Seed -> Dose -> Evaluation |
| `rl_planning` | RL, reinforcement learning, complex | CTV -> OAR -> Trajectory -> Seed(RL) -> CNN Dose -> Evaluation |
| `quick_planning` | quick, preview | CTV -> Trajectory -> Seed -> CNN Dose |
| `pancreas_segmentation` | pancreas, pancreatic cancer | CTV(pancreas) + OAR(pancreas) |
| `prostate_segmentation` | prostate, prostate cancer | CTV(prostate) + OAR(general) |
| `detailed_evaluation` | detailed evaluation, DVH | Evaluation -> DVH -> Constraints -> Scoring -> Report |

---

## Self-Evolution Process

```
User Interaction
    |
    v
+-------------------+
| InteractionMemory | Record all interactions
+--------+----------+
         |
         v
+-------------------+
|   SkillLearner    | Analyze patterns
|  - Tool sequences | Learn parameter preferences
|  - Trigger words  | Generate new skills
+--------+----------+
         |
         v
+-------------------+
| PreferenceStore   | Update preferences
|  SkillRegistry    | Update/create skills
+--------+----------+
         |
         v
    Evolution Complete
```

---

## Usage Examples

### Automatic Use in BrachyAgent

```python
from AgenticSys import BrachyAgent

agent = BrachyAgent(session_id="doctor_li")

# Normal usage
agent.run_preoperative_plan(ct_path="ct.nii.gz", mode="rule_based")

# Get recommended skill
skill = agent.get_recommended_skill("Generate treatment plan for prostate cancer patient")
if skill:
    print(f"Recommended: {skill['name']}")
    print(f"Tool sequence: {' -> '.join(skill['tool_sequence'])}")

# Trigger self-evolution
evolution = agent.evolve_from_interactions()
print(f"Learned {len(evolution['new_skills'])} new skills")
```

### Manual Evolution Trigger

```python
# After multiple interactions, manually trigger evolution
agent.evolve_from_interactions()

# View current skill status
for skill in agent.skill_registry.list_skills():
    print(f"{skill['name']}: success rate {skill['success_rate']:.0%}, used {skill['usage_count']} times")
```

---

## Data Storage

```
memory/
├── data/
│   ├── default/           # Default session data
│   │   ├── session.json   # Interaction history
│   │   ├── preferences.json  # User preferences
│   │   └── skills.json    # Learned skills
│   └── {session_id}/      # Per-session data
skills/
└── data/
    └── skills_registry.json  # Skill registry
```

---

## Evolution Strategies

| Strategy | Description |
|----------|-------------|
| **Minimum Occurrences** | Tool sequence must appear >= 3 times to be learned as a skill |
| **Success Rate Decay** | Skill failure reduces success rate by -10% |
| **Success Rate Boost** | Skill success increases success rate by +5% |
| **Confidence Threshold** | Preference confidence >= 0.7 to be auto-applied |
| **Skill Selection** | Recommended sorted by `success_rate * usage_count` |

---

*BrachyBot Memory & Skills System -- Making AI understand your habits better*
