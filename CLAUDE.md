# CLAUDE.md — line-simulation

## Project Overview

This repository is in an active transitional state. It currently serves as a **conceptual notes and design document** repository for an AI system architecture called **Aether** — a goal-conditioned, memory-augmented AI agent with intrinsic motivation, hierarchical planning, and persistent memory.

### Historical Context

The repository previously contained a full **Citrus Production Line Simulator** — a demand-driven, accumulator-controlled mass-flow simulation in Python with a tkinter GUI. That code was removed as the project shifted focus. The git history preserves the simulator implementation if it is needed again.

---

## Current Repository Structure

```
line-simulation/
└── README.md    # Design notes for the Aether AI system architecture
```

### README.md

Contains conceptual analysis of three core Aether system components:

1. **The Soul Module (Intrinsic Motivation)** — A synthetic dopamine / intrinsic reward engine. Curiosity spikes trigger proactive task generation based on misalignment between expected and observed states. Requires continual world-model updates. Uses negative reward for contradictions to force continuous refinement.

2. **The Persistent Fabric (Memory)** — A tiered memory hierarchy (Core / Recall / Archival) with Titans-style Surprise Gating (novelty-based write filter) and a Reflection Daemon (vector-space reindexer for offline semantic consolidation). Enables multi-session context continuity.

3. **The Compass (Hierarchical Planning)** — A goal-conditioned, multi-tiered planner:
   - **Executive Level**: Long-term objective maintenance
   - **Operational Level**: Token generation steering via local constraints
   - **Tactical Reasoner**: Divergence detection and recalibration (MCTS-style)

   Output is goal-conditioned with dynamic re-alignment — closed-loop control rather than feedforward completion.

---

## Historical Codebase: Citrus Production Line Simulator

Recoverable from git history (last live commit: `837d76d`). Key facts preserved here for context:

### Architecture

- **Hybrid simulation**: Continuous mass flow upstream, discrete fruit objects downstream
- **Demand-driven**: Accumulator fill levels control upstream speed multiplier (AUTO mode)
- **No physics engine**: Pure process modeling with discrete timesteps (default `dt=0.1s`)
- **Single file**: `production_line.py` (~1063 lines) with embedded tkinter GUI

### Data Flow Pipeline

```
Bin → Metering Belt → Unstacking → Grade Table(-15% juice) → Wash/Dry/Wax
    → Singulator(10 lanes, mass→fruit) → Camera/Cup(-10% recycle, -10% juice)
    → Accumulators(4) → PDGs(4) → Baggers(8) → Cases(30 lbs) → Pallets(60 cases)
```

### Key Constants

| Parameter | Value |
|---|---|
| Fruit weight | 0.21 lbs |
| Accumulator capacity | 3600 lbs each |
| Singulator lanes | 10, 720-fruit buffer each |
| PDGs | 4 (each feeding 2 baggers) |
| Bag sizes | 1, 2, 3, 5 lbs (one per PDG) |
| Case size | 30 lbs |
| Pallet size | 60 cases |
| Default timestep | 0.1 s |

### AUTO Control Thresholds

| Avg accumulator fill | Speed multiplier |
|---|---|
| < 20% | 1.0 |
| < 50% | 0.8 |
| < 80% | 0.5 |
| ≥ 80% | 0.0 |

### Classification

Uses golden-ratio quasi-random (`(i * 0.618) % 1.0`) instead of true RNG for determinism:
- 80% → PACK (routed to accumulators, round-robin)
- 10% → RECYCLE (re-enters singulator input)
- 10% → JUICE (discarded to juice stream)

### Classes (from `production_line.py`)

- `ProductionLineSimulator` — master orchestrator, runs the simulation loop
- `BulkFlowComponent` — generic rate-based component (max rate, yield loss, delay)
- `Lane` — singulator lane with circular buffer of 720 fruit
- `Accumulator` — buffer feeding a PDG, capacity 3600 lbs
- `Bagger` — consumes bags/min at fixed bag size, tracks partial bag accumulation
- `PDG` — packing density group, feeds 2 baggers from 1 accumulator
- `Bin` — finite fruit source with rate-limited dump
- `Fruit` — discrete fruit object post-singulation
- `SimulatorGUI` — tkinter controller/dashboard

### Dependencies (historical)

- **Python**: Standard library only (`dataclasses`, `typing`, `enum`, `json`, `random`, `tkinter`)
- **No test framework** configured

---

## Development Guidelines

### Git Workflow

- Develop on feature branches prefixed with `claude/`
- Commit messages should be clear and descriptive
- Push with `git push -u origin <branch-name>`
- Never push to `master` directly without explicit permission

### Code Conventions

- Keep code simple and focused; avoid over-engineering
- Prefer editing existing files over creating new ones
- Do not add docstrings, comments, or type annotations to code you did not change
- Only add comments where logic is non-obvious
- Python code uses `dataclass` and `enum` patterns — follow the same style if the simulator is restored
- Use `file_path:line_number` format when referencing code locations

### Recovering the Simulator

To restore the production line simulator from git history:

```bash
git show 837d76d:production_line.py > production_line.py
git show 42cb17c:.gitignore > .gitignore
```

The last known good README for the simulator is at commit `ebf24de` (before it was replaced):

```bash
git show ebf24de:README.md
```

---

## Notes for AI Assistants

- Always read existing files before proposing changes — do not assume file contents
- Use `TodoWrite` to plan and track multi-step tasks
- The `README.md` currently contains conceptual AI design notes, not project documentation
- The working simulator code does not currently exist on disk — recover from git if needed
- When restoring or extending the simulator, keep the Python and any JS implementations in sync
- Mass is tracked in lbs, rates in lbs/sec throughout the simulator
- Simulation uses fixed timestep (`dt_sec`, default 0.1 s) — never use wall-clock time inside the sim loop
