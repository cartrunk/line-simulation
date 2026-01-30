# CLAUDE.md — line-simulation

## Project Overview

**Citrus Production Line Simulator** — a demand-driven, accumulator-controlled mass-flow system that simulates a real citrus packing line. It tracks both continuous mass flow (lbs/sec) upstream and discrete fruit units (post-singulation) downstream to reproduce realistic throughput, buffering, and control behavior.

## Repository Structure

```
line-simulation/
├── CLAUDE.md                          # This file — AI assistant guidance
├── README.md                          # Full project documentation & architecture spec
├── production_line.py                 # Python simulator engine (578 lines)
└── production_line_dashboard.html     # Interactive browser-based dashboard (971 lines)
```

## Architecture

### Core Design

- **Hybrid simulation**: Continuous mass flow upstream, discrete fruit objects downstream
- **Demand-driven**: Accumulator fill levels control upstream speed multiplier (AUTO mode)
- **No physics engine**: Pure process modeling with discrete timesteps (default dt=0.1s)
- **Two implementations**: Python (canonical/backend) and JavaScript (embedded in HTML dashboard)

### Data Flow Pipeline

```
Bin → Metering Belt → Unstacking → Grade Table → Wash/Dry/Wax
    → Singulator (mass→fruit, 10 lanes) → Cup/Camera (classify)
    → Accumulators (4) → PDGs (4) → Baggers (8) → Cases → Pallets
```

Side streams: Grade table removes 15% to juice; camera classifies 10% recycle, 10% juice.

### Key Classes (production_line.py)

- `ProductionLineSimulator` — master orchestrator, runs the simulation loop (`production_line.py:185`)
- `BulkFlowComponent` — generic rate-based component with max rate, yield loss, delay (`production_line.py:37`)
- `Lane` — singulator lane with circular buffer of 720 fruit (`production_line.py:53`)
- `Accumulator` — buffer feeding a PDG, capacity 3600 lbs (`production_line.py:88`)
- `Bagger` — consumes bags/min at fixed bag size (`production_line.py:114`)
- `PDG` — packing density group, feeds 2 baggers from 1 accumulator (`production_line.py:148`)
- `Bin` — finite fruit source with rate-limited dump (`production_line.py:548`)
- `Fruit` — discrete fruit object post-singulation (`production_line.py:28`)

### Control Modes

- **AUTO**: Upstream speed multiplier derived from average accumulator fill %
  - `<20%` → 1.0, `<50%` → 0.8, `<80%` → 0.5, `≥80%` → 0.0
- **MANUAL**: Each component controlled independently via speed_pct

### Dashboard (production_line_dashboard.html)

- Self-contained HTML + JS (no build step)
- Uses Chart.js 3.9.1 from CDN for live charts
- Re-implements the simulator engine in JavaScript
- Controls: start/pause, reset, load bins, bagger speed/toggle, control mode
- Visualizes: accumulator fill bars, lane utilization, throughput chart, accumulator fill chart

## Development Guidelines

### Git Workflow

- Develop on feature branches prefixed with `claude/`
- Write clear, descriptive commit messages
- Push with `git push -u origin <branch-name>`

### Code Standards

- Keep code simple and focused; avoid over-engineering
- Prefer editing existing files over creating new ones
- Do not introduce security vulnerabilities (XSS, injection, etc.)
- Add comments only where logic is non-obvious
- Python code uses `dataclass` and `enum` patterns — follow the same style
- The HTML dashboard embeds all JS inline — no separate JS files or bundler

### Important Conventions

- Simulation uses fixed timestep (`dt_sec`, default 0.1s)
- Mass is tracked in lbs, rates in lbs/sec
- Fruit weight is 0.21 lbs
- 4 PDGs × 2 baggers = 8 total baggers; bag sizes are [1, 2, 3, 5] lbs
- 4 accumulators with 1:1 PDG mapping, each 3600 lbs capacity
- 10 singulator lanes, each with 720-fruit buffer capacity
- Classification uses golden-ratio quasi-random (`(i * 0.618) % 1.0`) instead of true RNG for determinism

## Build & Run

### Python

```bash
python production_line.py
```

Runs a 10-second simulation (100 steps at dt=0.1s) and prints state + metrics as JSON.

### Dashboard

Open `production_line_dashboard.html` directly in a browser. No server or build step needed.

### Dependencies

- **Python**: Standard library only (dataclasses, typing, enum, json)
- **Dashboard**: Chart.js 3.9.1 (loaded from CDN)

### Testing

No test framework configured yet. The README defines validation scenarios:
1. Demand-driven behavior (accumulators stabilize ~50% fill in AUTO)
2. Overflow prevention (accumulators cap, upstream stops)
3. Recycle loop bottleneck (singulator becomes limiting)
4. Manual control (AUTO multiplier ignored)

## Notes for AI Assistants

- Always read existing code before proposing changes
- Use TodoWrite to plan multi-step tasks
- Reference files with `file_path:line_number` format
- Keep changes minimal and directly relevant to the request
- The Python and JS implementations should stay in sync — changes to simulation logic need to be reflected in both
- The README.md serves as the authoritative spec; consult it for expected behavior and tuning parameters
