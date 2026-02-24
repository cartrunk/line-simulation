from __future__ import annotations
import asyncio
import json
import time

from .types import AetherState, Plan, Goal
from .memory import MemoryFabric
from .soul import Soul
from .planner import build_planner
from .llm import ping, llm_complete


# ---------------------------------------------------------------------------
# State initialisation
# ---------------------------------------------------------------------------

def initialize_state(memory: MemoryFabric) -> AetherState:
    return AetherState(
        core_directives=[
            "Seek truth without sycophancy.",
            "Be genuinely useful to the user.",
            "Continuously refine understanding.",
        ],
        active_goals=[],
        current_plan=Plan(),
        memory_snapshot=memory.empty_snapshot(),
        last_reflection=time.time(),
        surprise_score=0.0,
        action_history=[],
    )


# ---------------------------------------------------------------------------
# User message handler
# ---------------------------------------------------------------------------

async def handle_user_input(
    user_input: str,
    state: AetherState,
    memory: MemoryFabric,
) -> str:
    await memory.update(state, user_input)

    prompt = (
        f"The user said: \"{user_input}\"\n\n"
        f"Memory: {state['memory_snapshot']['core']}\n\n"
        f"Decide: is this a simple question or a multi-step task?\n"
        f"- If simple, answer directly.\n"
        f"- If multi-step, capture it as a goal.\n\n"
        f"Output ONLY valid JSON — one of:\n"
        f'  {{"is_task": false, "answer": "..."}}\n'
        f'  {{"is_task": true, "goal": "...", "priority": 0.XX, "milestones": ["..."]}}'
    )
    raw = await llm_complete(prompt)
    raw = raw.strip().strip("```json").strip("```").strip()
    data = json.loads(raw)

    if data.get("is_task"):
        goal = Goal(
            description=data["goal"],
            priority=float(data.get("priority", 0.7)),
            milestones=data.get("milestones", []),
        )
        state["active_goals"].append(goal)
        return f"[Aether] Goal accepted: {goal.description}"

    return f"[Aether] {data.get('answer', '(no answer)')}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def aether_main_loop() -> None:
    print("Connecting to LM Studio...")
    if not await ping():
        print(
            "ERROR: Cannot reach LM Studio at http://127.0.0.1:1234\n"
            "Make sure LM Studio is running, a model is loaded, and the server is started."
        )
        return

    print("LM Studio connected.\n")

    memory = MemoryFabric()
    soul = Soul(memory)
    planner = build_planner()
    state = initialize_state(memory)
    planner_config = {"configurable": {"thread_id": "aether_persistent"}}

    # Soul runs in the background, emitting intrinsic goals autonomously
    asyncio.create_task(soul.background_cycle(state))

    print("Aether is running. Type your message or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nShutting down.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        response = await handle_user_input(user_input, state, memory)
        print(response)

        if state["active_goals"]:
            print("[Planner] Building plan...")
            state = await planner.ainvoke(state, config=planner_config)
            plan = state["current_plan"]
            if plan.root:
                print(f"[Planner] {plan.root}")
                for sub in plan.tactical:
                    print(f"  Goal: {sub.goal} (confidence={sub.confidence:.0%})")
                    for step in sub.steps:
                        print(f"    • {step}")
            print()


if __name__ == "__main__":
    asyncio.run(aether_main_loop())
