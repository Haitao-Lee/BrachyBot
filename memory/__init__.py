"""
BrachyBot Memory System
======================
Self-evolving memory that learns from user interactions to develop
personalized skills and improve agent behavior over time.

Architecture inspired by:
- GenericAgent: Layered memory (L0-L4), contextual information density
- Reflexion: Trajectory-based self-reflection with episodic memory
- Hermes Agent: Dialectic user profiling (Honcho-style)
- EvoSkills: Co-evolutionary skill verification
"""

from .interaction_memory import InteractionMemory
from .skill_learner import SkillLearner
from .preference_store import PreferenceStore
from .experience_memory import ExperienceMemory, ExperienceEntry
from .self_evolution import SelfEvolutionEngine
from .layered_memory import LayeredMemory, MetaRule, InsightEntry, GlobalFact, SOP, SOPStep, SessionArchive
from .reflexion_engine import ReflexionEngine, ReflexionEntry, EpisodicMemory
from .context_optimizer import ContextDensityOptimizer, ContextSegment
from .user_profile import UserProfile, PreferenceDimension, InteractionPattern
from .skill_crystallizer import SkillCrystallizer, CrystallizedSkill, EvolutionCycle

__all__ = [
    # Original
    "InteractionMemory",
    "SkillLearner",
    "PreferenceStore",
    "ExperienceMemory",
    "ExperienceEntry",
    "SelfEvolutionEngine",
    # Layered Memory (GenericAgent-inspired)
    "LayeredMemory",
    "MetaRule",
    "InsightEntry",
    "GlobalFact",
    "SOP",
    "SOPStep",
    "SessionArchive",
    # Reflexion Engine
    "ReflexionEngine",
    "ReflexionEntry",
    "EpisodicMemory",
    # Context Optimizer
    "ContextDensityOptimizer",
    "ContextSegment",
    # User Profile
    "UserProfile",
    "PreferenceDimension",
    "InteractionPattern",
    # Skill Crystallizer
    "SkillCrystallizer",
    "CrystallizedSkill",
    "EvolutionCycle",
]
