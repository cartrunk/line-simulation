# Aether Core System

A single persistent runtime process. Base LLM (any tool-calling model) is treated as a stateless cognitive substrate. All autonomy lives in four tightly coupled modules that share a single typed state object.

---

## LLM Backend – Local LM Studio

Aether uses a local LM Studio instance as its cognitive substrate. LM Studio exposes an OpenAI-compatible REST API, so the standard `openai` Python client works with no additional dependencies.

```python
from openai import AsyncOpenAI

# LM Studio default endpoint
llm = AsyncOpenAI(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",  # required by client but not validated locally
)

# model name must match whatever is loaded in LM Studio
LLM_MODEL = "local-model"  # replace with your loaded model's identifier
```

All `llm.complete(...)` calls throughout Aether map to:

```python
async def llm_complete(prompt: str, context: dict = None) -> str:
    messages = []
    if context:
        messages.append({"role": "system", "content": str(context)})
    messages.append({"role": "user", "content": prompt})

    response = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content
```

For tool-calling nodes (operational ReAct loop), pass `tools=` to the same client:

```python
response = await llm.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=tool_schemas,      # OpenAI-format tool definitions
    tool_choice="auto",
)
```

> **Note:** Tool calling requires a model that supports it (e.g. a fine-tuned instruct model with function-calling capability). Check LM Studio's model card before enabling.

---

```python
from typing import TypedDict, List, Dict, Optional
from dataclasses import dataclass
import asyncio

class AetherState(TypedDict):
    # persistent across all cycles
    core_directives: List[str]          # fixed xAI-style anchors
    active_goals: List[Goal]            # high-level objectives
    current_plan: Plan                  # hierarchical tree
    memory_snapshot: MemorySnapshot     # compact view of LTM
    last_reflection: float              # unix timestamp
    surprise_score: float               # 0-1 novelty
    action_history: List[ActionTrace]   # last N steps for OODA
```

```python
@dataclass
class Goal:
    id: str
    description: str
    priority: float          # computed by Soul
    milestones: List[str]
    deadline: Optional[float]

@dataclass
class Plan:
    root: str                # strategic objective
    tactical: List[SubPlan]  # current active branches
    status: Dict[str, str]   # milestone → "pending|active|done|failed"

@dataclass
class SubPlan:
    goal: str
    steps: List[str]         # token-level or tool-level
    confidence: float
```

---

## 1. Soul Module – Intrinsic Motivation Engine

Runs in its own async loop. Never waits for external input.

```python
class Soul:
    def __init__(self, memory: MemoryFabric, world_model: WorldModel):
        self.memory = memory
        self.world_model = world_model  # tiny forward-only net (70M) for prediction error

    async def background_cycle(self, state: AetherState):
        while True:
            await asyncio.sleep(300)  # or event-driven on new ingest

            recent_episodes = await self.memory.recall_top_k(20)
            surprise = self.world_model.compute_prediction_error(recent_episodes)
            learning_progress = self.compute_delta_competence(state)

            new_goal = await self.generate_internal_goal(surprise, learning_progress, state)

            if new_goal.priority > 0.65:
                state["active_goals"].append(new_goal)
                # immediately trigger planner
                await self.inject_into_planner(new_goal, state)
```

`generate_internal_goal` prompt (internal only):

```
You are the intrinsic drive of Aether.
Current user profile summary: {memory.user_profile}
Recent novelty: {surprise:.2f}
Recent learning progress: {learning_progress:.2f}
Core directive: Understand the universe, seek truth, be useful without sycophancy.
Propose ONE new goal that is proactive and unprompted.
Output only JSON: {"description": "...", "priority": 0.XX, "milestones": [...]}
```

---

## 2. Memory Fabric – Persistent State (Letta-style with extensions)

Three live tiers, all managed by the LLM itself via tool calls.

```python
class MemoryFabric:
    async def update(self, state: AetherState, new_observation: str):
        # surprise gate
        surprise = self.compute_surprise(new_observation, state["memory_snapshot"])
        if surprise > 0.4 or len(state["action_history"]) % 5 == 0:
            summary = await self.llm_reflect(new_observation, state)

            # Tier 1 – Core (always in context)
            state["memory_snapshot"]["core"] = await self.refresh_core_block(summary)

            # Tier 2 – Recall (vector)
            await self.vector_store.upsert(summary, metadata={"ts": time.time()})

            # Tier 3 – Episodic Graph (Neo4j or in-memory for MVP)
            await self.graph.upsert_relations(extract_triples(summary))

            # token-space learning (Context Repository style)
            await self.commit_context_repository(summary)
```

Reflection tool the LLM calls on itself:

```python
async def llm_reflect(observation: str, state):
    prompt = f"""
    Reflect on this new observation in <1k tokens:
    {observation}
    Update only:
    - core_persona_delta
    - key_facts_to_store
    - contradictions_with_existing_graph
    """
    return await llm.complete(prompt, state["memory_snapshot"])
```

---

## 3. Hierarchical Planner – Persistent Compass

Implemented as nested LangGraph. State is checkpointed after every node.

```python
from langgraph.graph import StateGraph, END

def build_hierarchical_graph():
    workflow = StateGraph(AetherState)

    # Level 0: Executive
    workflow.add_node("executive", executive_node)      # decomposes goals

    # Level 1: Tactical (one per milestone)
    workflow.add_node("tactical", tactical_node)        # spawns sub-graphs

    # Level 2: Operational (ReAct)
    workflow.add_node("operational", operational_react)

    # edges with persistent routing
    workflow.add_conditional_edges(
        "executive",
        route_to_tactical,
        {"tactical": "tactical", "done": END}
    )

    return workflow.compile(checkpointer=MemorySaver())  # persists entire state tree
```

`executive_node` simply runs the LLM with:
- current `active_goals`
- `memory_snapshot`
- instruction: "Decompose into milestones or mark complete"

---

## 4. Agency Loop – The Body (full OODA inside every operational step)

```python
async def operational_react(state: AetherState) -> AetherState:
    while True:
        # Orient
        context = compile_full_context(state)  # core + recall + graph slice

        # Decide
        action = await llm_decide(context, state["current_plan"].tactical[0])

        if action.is_final:
            break

        # Act
        result = await execute_tool_safely(action.tool, action.args)

        # Observe
        observation = process_tool_output(result)

        # Reflect & update ALL layers
        await soul.memory.update(state, observation)   # surprise-gated
        await update_plan_status(state, observation)

        # trace
        state["action_history"].append(ActionTrace(action, observation))

        if len(state["action_history"]) > 50:
            state["action_history"] = state["action_history"][-50:]

    return state
```

---

## Full Autonomous Cycle

How the four modules close the loop:

1. Soul wakes → computes surprise → emits Goal
2. Goal injected → Hierarchical Planner checkpoints new Plan
3. Planner routes to first tactical sub-graph → spawns operational ReAct loop
4. Every ReAct step:
   - reads from Memory Fabric
   - writes back via surprise gate
   - Soul monitors in background for new intrinsic triggers
5. When plan completes or stalls: reflection daemon runs, commits to Context Repository, updates core memory

**Result:**
- Prompt-dependence gone: Soul starts cycles alone
- No persistent state gone: MemoryFabric is the single source of truth, updated in place
- Stateless sampling gone: Planner + checkpointed state acts as persistent prior for every token
- No interaction agency gone: OODA loop modifies environment, observes, and folds feedback into LTM and Planner in one atomic step

---

## Minimal Runnable Skeleton

```python
async def aether_main_loop():
    state: AetherState = initialize_empty_state()
    memory = MemoryFabric()
    soul = Soul(memory, WorldModel())
    graph = build_hierarchical_graph()

    # start intrinsic background
    asyncio.create_task(soul.background_cycle(state))

    while True:
        # either user message or internal goal already present
        if state["active_goals"]:
            config = {"configurable": {"thread_id": "aether_persistent"}}
            state = await graph.ainvoke(state, config=config)
```
