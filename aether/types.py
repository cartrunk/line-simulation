from __future__ import annotations
from typing import TypedDict, List, Dict, Optional, Any
from dataclasses import dataclass, field
import uuid
import time


@dataclass
class Goal:
    description: str
    priority: float
    milestones: List[str] = field(default_factory=list)
    deadline: Optional[float] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SubPlan:
    goal: str
    steps: List[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class Plan:
    root: str = ""
    tactical: List[SubPlan] = field(default_factory=list)
    status: Dict[str, str] = field(default_factory=dict)  # milestone → pending|active|done|failed


@dataclass
class ActionTrace:
    tool: str
    args: Dict[str, Any]
    result: str
    timestamp: float = field(default_factory=time.time)


class MemorySnapshot(TypedDict):
    core: str             # always-in-context compressed summary (~300 words)
    user_profile: str     # running model of the user


class AetherState(TypedDict):
    core_directives: List[str]
    active_goals: List[Goal]
    current_plan: Plan
    memory_snapshot: MemorySnapshot
    last_reflection: float
    surprise_score: float
    action_history: List[ActionTrace]
