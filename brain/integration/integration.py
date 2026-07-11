"""
Brain-Tool Integration Layer
============================
Bridges the brain decision system with the tool_factory tools.
Enables LLM-driven tool chain planning and execution.
"""

import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


class BrainToolBridge:
    """
    Connects the brain system (deciders, planner, executor) with
    the tool_factory tool implementations.
    """

    def __init__(self):
        self._tool_factories: Dict[str, Callable] = {}
        self._tool_instances: Dict[str, Any] = {}
        self._brain_registry = None
        self._plan_executor = None

    def register_tool_factory(self, name: str, factory_fn: Callable) -> None:
        """Register a tool factory function that creates tool instances."""
        self._tool_factories[name] = factory_fn

    def create_tool_instance(self, name: str, **kwargs) -> Any:
        """Create a tool instance using its registered factory."""
        if name not in self._tool_factories:
            raise ValueError(f"No factory registered for tool: {name}")
        instance = self._tool_factories[name](**kwargs)
        self._tool_instances[name] = instance
        return instance

    def set_brain_registry(self, registry) -> None:
        """Set the brain's ToolRegistry for LLM planning."""
        self._brain_registry = registry

    def set_plan_executor(self, executor) -> None:
        """Set the brain's PlanExecutor for plan execution."""
        self._plan_executor = executor

    def initialize_brain_tools(self) -> None:
        """Initialize all registered tool factories and register with brain."""
        if self._brain_registry is None:
            raise RuntimeError("Brain registry not set")

        for name, factory_fn in self._tool_factories.items():
            try:
                instance = factory_fn()
                self._tool_instances[name] = instance
                self._brain_registry.register(
                    name=name,
                    description=instance.description,
                    category=getattr(instance, 'category', 'general'),
                    parameters=instance.input_schema,
                    execute_fn=lambda n=name, **kw: self._tool_instances[n].execute(**kw)
                )
                logger.info(f"Registered tool with brain: {name}")
            except Exception as e:
                logger.error(f"Failed to register tool {name}: {e}")

    def get_tool(self, name: str) -> Optional[Any]:
        """Get a tool instance by name."""
        return self._tool_instances.get(name)

    def execute_via_brain(self, plan: Dict[str, Any],
                          context: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a plan using the brain's PlanExecutor."""
        if self._plan_executor is None:
            raise RuntimeError("Plan executor not set")
        return self._plan_executor.execute_plan(plan, context)


def create_ctv_segmentation_tool(anatomy: str):
    """Factory for CTV segmentation tools."""
    from tool_factory.CTV_seg import TOOL_REGISTRY as CTV_REGISTRY

    key_map = {
        "pancreatic": "pancreatic_tumor",
        "liver": "liver_tumor",
        "kidney": "kidney_tumor",
        "prostate": "prostate_tumor",
        "lung": "lung_tumor",
        "voco_pancreatic": "voco_pancreatic",
        "voco_liver": "voco_liver",
        "voco_kidney": "voco_kidney",
        "voco_lung": "voco_lung",
        "voco_colon": "voco_colon",
    }

    tool_key = key_map.get(anatomy.lower())
    if tool_key is None:
        tool_key = anatomy.lower()

    tool_class = CTV_REGISTRY.get(tool_key)
    if tool_class is None:
        raise ValueError(f"Unknown anatomy: {anatomy}. Available: {list(CTV_REGISTRY.keys())}")
    return tool_class()


def create_oar_segmentation_tool(anatomy: str):
    """Factory for OAR segmentation tools."""
    from tool_factory.OAR_seg.pancreatic_oar import PancreaticOARTool
    from tool_factory.OAR_seg.totalsegmentator_oar import TotalSegmentatorOARTool
    from tool_factory.OAR_seg.voco_total_segmentation import VoCoTotalSegmentatorTool
    from tool_factory.OAR_seg.aorta_vessel_voco import VoCoAortaVesselTool

    tools = {
        "totalsegmentator": TotalSegmentatorOARTool,
        "pancreatic": PancreaticOARTool,
        "voco": VoCoTotalSegmentatorTool,
        "aorta": VoCoAortaVesselTool,
    }
    tool_class = tools.get(anatomy.lower())
    if tool_class is None:
        raise ValueError(f"Unknown anatomy: {anatomy}. Available: {list(tools.keys())}")
    return tool_class()


def create_seed_planning_tool(mode: str = "rule_based"):
    """Factory for seed planning tools."""
    from tool_factory.seed_plan import SeedPlanningTool, RuleBasedSeedPlanningTool, RLSeedPlanningTool

    tools = {
        "unified": SeedPlanningTool,
        "rule_based": RuleBasedSeedPlanningTool,
        "rl": RLSeedPlanningTool,
    }
    tool_class = tools.get(mode.lower())
    if tool_class is None:
        raise ValueError(f"Unknown mode: {mode}. Available: {list(tools.keys())}")
    return tool_class()


_BRIDGE: Optional[BrainToolBridge] = None


def get_bridge() -> BrainToolBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = BrainToolBridge()
    return _BRIDGE


def initialize_brain_integration(bridge: Optional[BrainToolBridge] = None) -> BrainToolBridge:
    """
    Initialize the brain-tool bridge with standard tool factories.
    Returns the configured bridge.
    """
    b = bridge or get_bridge()

    b.register_tool_factory("pancreatic_ctv", lambda: create_ctv_segmentation_tool("pancreatic"))
    b.register_tool_factory("liver_ctv", lambda: create_ctv_segmentation_tool("liver"))
    b.register_tool_factory("kidney_ctv", lambda: create_ctv_segmentation_tool("kidney"))
    b.register_tool_factory("prostate_ctv", lambda: create_ctv_segmentation_tool("prostate"))
    b.register_tool_factory("lung_ctv", lambda: create_ctv_segmentation_tool("lung"))

    b.register_tool_factory("voco_pancreatic_ctv", lambda: create_ctv_segmentation_tool("voco_pancreatic"))
    b.register_tool_factory("voco_liver_ctv", lambda: create_ctv_segmentation_tool("voco_liver"))
    b.register_tool_factory("voco_kidney_ctv", lambda: create_ctv_segmentation_tool("voco_kidney"))
    b.register_tool_factory("voco_lung_ctv", lambda: create_ctv_segmentation_tool("voco_lung"))
    b.register_tool_factory("voco_colon_ctv", lambda: create_ctv_segmentation_tool("voco_colon"))

    b.register_tool_factory("totalsegmentator_oar", lambda: create_oar_segmentation_tool("totalsegmentator"))
    b.register_tool_factory("pancreatic_oar", lambda: create_oar_segmentation_tool("pancreatic"))
    b.register_tool_factory("voco_oar", lambda: create_oar_segmentation_tool("voco"))
    b.register_tool_factory("aorta_vessel_oar", lambda: create_oar_segmentation_tool("aorta"))

    b.register_tool_factory("unified_seed", lambda: create_seed_planning_tool("unified"))
    b.register_tool_factory("rule_based_seed", lambda: create_seed_planning_tool("rule_based"))
    b.register_tool_factory("rl_seed", lambda: create_seed_planning_tool("rl"))

    return b
