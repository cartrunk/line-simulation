# CLAUDE.md — line-simulation

## Project Overview

This repository contains conceptual design notes for **Aether** — a goal-conditioned, memory-augmented AI agent architecture with intrinsic motivation, hierarchical planning, and persistent memory.

## Repository Structure

```
line-simulation/
└── README.md    # Aether system architecture design notes
```

## README.md Contents

Three core system components:

1. **The Soul Module (Intrinsic Motivation)** — A synthetic dopamine / intrinsic reward engine. Curiosity spikes trigger proactive task generation based on misalignment between expected and observed states. Uses negative reward for contradictions to drive continuous refinement rather than surface-level completion.

2. **The Persistent Fabric (Memory)** — A tiered memory hierarchy (Core / Recall / Archival) with Titans-style Surprise Gating (novelty-based write filter) and a Reflection Daemon (vector-space reindexer for offline semantic consolidation, analogous to REM sleep). Enables multi-session context continuity.

3. **The Compass (Hierarchical Planning)** — A goal-conditioned, multi-tiered planner:
   - **Executive Level**: Long-term objective maintenance
   - **Operational Level**: Token generation steering via local constraints and corrective reasoning
   - **Tactical Reasoner**: Divergence detection and recalibration (MCTS-style search heuristics)

   Output is goal-conditioned with dynamic re-alignment — closed-loop control rather than feedforward next-token completion.

## Development Guidelines

- Develop on feature branches prefixed with `claude/`
- Push with `git push -u origin <branch-name>`
- Prefer editing existing files over creating new ones
- Keep changes minimal and directly relevant to the request

## Notes for AI Assistants

- Read existing files before proposing changes
- Use `TodoWrite` to plan and track multi-step tasks
- `README.md` is the primary and only source document in this repository
