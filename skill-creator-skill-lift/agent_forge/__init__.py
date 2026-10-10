"""agent_forge: an agent that builds voice agents from an SOP, tests them in simulation,
repairs them with evidence, and proves its tests catch regressions."""

from .extract import RuleExtractor
from .forge import ForgeResult, forge
from .mutate import mutation_test
from .repair import repair
from .simulate import run_suite
from .sop import load_sop, parse_sop
from .spec import AgentSpec, validate

__all__ = [
    "AgentSpec",
    "ForgeResult",
    "RuleExtractor",
    "forge",
    "load_sop",
    "mutation_test",
    "parse_sop",
    "repair",
    "run_suite",
    "validate",
]
