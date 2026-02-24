from __future__ import annotations
import asyncio
from typing import Callable, Awaitable, Optional

from .config import SOUL_CYCLE_SECONDS, GOAL_PRIORITY_THRESHOLD
from .types import AetherState, Goal
from .memory import MemoryFabric
from .llm import llm_complete, extract_json


class Soul:
    def __init__(self, memory: MemoryFabric):
        self.memory = memory

    def compute_delta_competence(self, state: AetherState) -> float:
        """Proxy for learning progress: fraction of plan milestones marked done."""
        status = state["current_plan"].status
        if not status:
            return 0.0
        done = sum(1 for v in status.values() if v == "done")
        return done / len(status)

    async def generate_internal_goal(
        self,
        surprise: float,
        learning_progress: float,
        state: AetherState,
    ) -> Goal:
        active_descriptions = [g.description for g in state["active_goals"]]
        prompt = (
            f"You are the intrinsic drive of Aether.\n\n"
            f"Memory summary: {state['memory_snapshot']['core']}\n"
            f"User profile: {state['memory_snapshot']['user_profile']}\n"
            f"Recent novelty score: {surprise:.2f}\n"
            f"Recent learning progress: {learning_progress:.2f}\n"
            f"Core directive: Understand the world, seek truth, be genuinely useful without sycophancy.\n"
            f"Currently active goals: {active_descriptions}\n\n"
            f"Propose ONE new proactive goal not already in the active list.\n"
            f'Output ONLY valid JSON: {{"description": "...", "priority": 0.XX, "milestones": ["...", "..."]}}'
        )
        raw = await llm_complete(prompt)
        data = extract_json(raw)
        return Goal(
            description=data["description"],
            priority=float(data["priority"]),
            milestones=data.get("milestones", []),
        )

    async def background_cycle(
        self,
        state: AetherState,
        on_new_goal: Optional[Callable[[Goal, AetherState], Awaitable[None]]] = None,
    ) -> None:
        """Runs indefinitely. Emits intrinsic goals when novelty or learning progress warrants it."""
        while True:
            await asyncio.sleep(SOUL_CYCLE_SECONDS)
            surprise = state["surprise_score"]
            learning_progress = self.compute_delta_competence(state)

            try:
                goal = await self.generate_internal_goal(surprise, learning_progress, state)
                if goal.priority > GOAL_PRIORITY_THRESHOLD:
                    print(
                        f"[Soul] New intrinsic goal: {goal.description!r} "
                        f"(priority={goal.priority:.2f})"
                    )
                    state["active_goals"].append(goal)
                    if on_new_goal:
                        await on_new_goal(goal, state)
            except Exception as exc:
                print(f"[Soul] Goal generation error: {exc}")
