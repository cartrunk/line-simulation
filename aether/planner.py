from __future__ import annotations
import json

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .types import AetherState, Plan, SubPlan
from .llm import llm_complete


# ---------------------------------------------------------------------------
# Node: Executive — decomposes the highest-priority goal into a Plan
# ---------------------------------------------------------------------------

async def executive_node(state: AetherState) -> AetherState:
    if not state["active_goals"]:
        return state

    goal = state["active_goals"][0]
    prompt = (
        f"You are the executive planner of Aether.\n\n"
        f"Current goal: {goal.description}\n"
        f"Milestones: {goal.milestones}\n"
        f"Memory: {state['memory_snapshot']['core']}\n"
        f"Current plan status: {state['current_plan'].status}\n\n"
        f"Decompose this goal into a concrete tactical plan.\n"
        f"Output ONLY valid JSON:\n"
        f'{{\n'
        f'  "root": "strategic objective",\n'
        f'  "tactical": [\n'
        f'    {{"goal": "sub-goal", "steps": ["step1", "step2"], "confidence": 0.XX}}\n'
        f'  ],\n'
        f'  "status": {{"milestone_name": "pending"}}\n'
        f"}}"
    )
    raw = await llm_complete(prompt)
    raw = raw.strip().strip("```json").strip("```").strip()
    data = json.loads(raw)

    state["current_plan"] = Plan(
        root=data["root"],
        tactical=[SubPlan(**t) for t in data["tactical"]],
        status=data.get("status", {}),
    )
    return state


# ---------------------------------------------------------------------------
# Node: Tactical — reviews and tightens the first sub-plan's steps
# ---------------------------------------------------------------------------

async def tactical_node(state: AetherState) -> AetherState:
    if not state["current_plan"].tactical:
        return state

    sub = state["current_plan"].tactical[0]
    prompt = (
        f"You are the tactical coordinator of Aether.\n\n"
        f"Sub-plan goal: {sub.goal}\n"
        f"Draft steps: {sub.steps}\n"
        f"Memory: {state['memory_snapshot']['core']}\n\n"
        f"Review and refine these steps so they are concrete and executable.\n"
        f'Output ONLY valid JSON: {{"steps": ["step1", "step2"], "confidence": 0.XX}}'
    )
    raw = await llm_complete(prompt)
    raw = raw.strip().strip("```json").strip("```").strip()
    data = json.loads(raw)

    state["current_plan"].tactical[0].steps = data["steps"]
    state["current_plan"].tactical[0].confidence = float(data["confidence"])
    return state


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_from_executive(state: AetherState) -> str:
    if state["active_goals"] and state["current_plan"].tactical:
        return "tactical"
    return "done"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_planner() -> any:
    workflow = StateGraph(AetherState)

    workflow.add_node("executive", executive_node)
    workflow.add_node("tactical", tactical_node)

    workflow.set_entry_point("executive")
    workflow.add_conditional_edges(
        "executive",
        route_from_executive,
        {"tactical": "tactical", "done": END},
    )
    workflow.add_edge("tactical", END)

    return workflow.compile(checkpointer=MemorySaver())
