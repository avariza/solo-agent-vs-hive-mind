# Hive Mind vs Solo Agent

**AI Tinkerers Montreal — April 2026 Demo**

A live race between two Claude Code agents solving the same Python coding
challenge. The only structural difference is which **model** each side runs:
you configure `SOLO_MODEL` and `HIVE_MODEL` in `.env` and watch the
trade-off between speed, cost, and correctness unfold in real time.

## Quick Start

```bash
# 1. One-time setup (Python venv, ruflo, scoreboard deps, radon)
bash scripts/setup.sh

# 2. Pick your models (edit .env)
#    SOLO_MODEL=haiku
#    HIVE_MODEL=opus

# 3. Start the scoreboard (leave running in its own terminal)
cd scoreboard && npm start

# 4. Run the race
bash scripts/race.sh

# Faster variant (~90s per side, 6 probes instead of 8)
DEMO_MODE=fast bash scripts/race.sh
```

Open `http://localhost:3000` for the live scoreboard.

## What Happens

Both sides receive the **same prompt** and the **same challenge** (a weighted,
thread-safe sliding-window rate limiter in Python). They run in parallel
from a synchronized starting gun. The differences are:

| | Solo Agent | Hive Mind |
|---|---|---|
| Model | `$SOLO_MODEL` from `.env` | `$HIVE_MODEL` from `.env` |
| Coordination | None — a single `claude -p` session | `ruflo hive-mind init` + `spawn` registers hierarchical/raft topology before the same `claude -p` runs |
| Prompt | Short, identical | Short, identical |
| Token/cost tracking | `stream_parse.py` → `scoreboard/solo.usage.json` | `stream_parse.py` → `scoreboard/hive.usage.json` |

The honest experiment is: **given identical inputs, does the more expensive
model (or the coordinated topology) produce a materially better solution,
and is the delta worth the cost?** The scoreboard surfaces tokens, dollars,
and score side-by-side so you can answer that live.

### Why no multi-phase handoff any more

Earlier versions forced the hive through an ARCHITECT → CODER+TESTER →
REVIEWER protocol with an intermediate `ARCHITECT_HANDOFF.md` artifact and
animated phase banners. That made for good theatre but conflated two
variables (prompt complexity + model choice), so we removed it. Now the
only knob you tune is the model — the comparison is clean.

## Model Selection (`.env`)

```bash
# Accepted values:
#   - Alias:    "haiku" | "sonnet" | "opus"
#   - Full id:  "claude-opus-4-6"
#               "claude-sonnet-4-5-20250929"
#               "claude-haiku-4-5-20251001"
#   - Blank:    use Claude Code's built-in default

SOLO_MODEL=haiku
HIVE_MODEL=opus
```

Both `scripts/solo.sh` and `scripts/hive.sh` source `.env` at startup and
pass the value via `claude --model`. Leave either variable blank to use
the CLI's default model.

**Fun configurations to try:**

| `SOLO_MODEL` | `HIVE_MODEL` | What you're testing |
|---|---|---|
| `haiku` | `opus` | Price/quality frontier — is Opus worth ~15× the cost? |
| `sonnet` | `sonnet` | Pure "coordination overhead" isolation |
| `haiku` | `haiku` | How good is the cheap model *alone*? |
| `opus` | `haiku` | Reversed — does Opus-solo beat Haiku-in-a-hive? |

## Scoring (100 points, redistributed for senior-dev signal)

| Metric | Points | Source |
|---|---|---|
| Implementation present | 10 | file exists |
| Tests present | 10 | file exists |
| Test pass rate | up to 30 | `pytest` result |
| Coverage (continuous) | up to 10 | `pytest-cov` |
| Coverage ≥ 80% bonus | 5 | flat bonus |
| Behavioral probes | up to 15 | `scoreboard/probes.py` (8 hidden edge cases, 6 in fast mode) |
| Conciseness (impl+test LOC, gated by correctness) | up to 10 | `evaluate.js` |
| Max cyclomatic complexity (radon) | up to 5 | `scoreboard/metrics.py` |
| Throughput (ops/sec under contention) | up to 5 | `scoreboard/metrics.py` |
| **Model / tokens / cost** | display only | `stream_parse.py` → `*.usage.json` |

The probes are behavioral — they exercise weighted cost accounting,
sliding-window expiry, concurrent grants under `threading.Barrier`, and
stale-client eviction. Passing "all tests" isn't enough if a hidden probe
finds a race condition.

**Conciseness and throughput are gated by correctness** (`min(test-pass-rate,
probe-ratio)`) so a broken 3-line stub can't game them. Complexity is
raw (lower `max_cc` → more points) because seniors want to see whether
`allow_request` stayed O(1) in branches.

## Project Structure

```
├── .env                        # SOLO_MODEL / HIVE_MODEL
├── challenge/
│   ├── CHALLENGE.md            # The identical prompt both sides receive
│   ├── CHALLENGE_FAST.md       # Trimmed variant for DEMO_MODE=fast
│   ├── solo/                   # Solo agent workspace (src/ pre-created)
│   └── hive/                   # Hive mind workspace (src/ pre-created)
├── scoreboard/
│   ├── server.js               # SSE server watching both workspaces
│   ├── index.html              # Live dashboard
│   ├── evaluate.js             # Post-race scoring
│   ├── probes.py               # 8 behavioral correctness probes
│   ├── metrics.py              # radon complexity + threaded throughput
│   ├── solo.usage.json         # Per-side token/cost summary (generated)
│   └── hive.usage.json         # ditto
├── scripts/
│   ├── setup.sh                # One-time install
│   ├── race.sh                 # Clean workspaces, launch both sides, score
│   ├── solo.sh                 # Solo agent launcher (reads SOLO_MODEL)
│   ├── hive.sh                 # Hive launcher (reads HIVE_MODEL, ruflo init)
│   ├── score.sh                # Re-score an already-completed run
│   ├── clean.sh                # Nuke all race artifacts
│   └── stream_parse.py         # Parses claude stream-json → usage summary
└── README.md
```

## Scripts

| Script | Purpose |
|--------|---------|
| `setup.sh` | Install Python deps (pytest, radon), ruflo, scoreboard deps |
| `race.sh` | Clean, launch both sides in parallel at a synchronized starting gun, then score |
| `solo.sh` | Launch the solo agent (reads `.env`, uses `$SOLO_MODEL`) |
| `hive.sh` | Launch the hive mind (reads `.env`, uses `$HIVE_MODEL`, inits ruflo topology) |
| `score.sh` | Re-run `evaluate.js` on existing outputs (useful after editing scoring) |
| `clean.sh` | Remove all race artifacts, logs, usage files |

## Prerequisites

- Node.js 20+
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- ruflo (auto-installed by `setup.sh`)

## Demo Day Checklist

- [ ] `bash scripts/setup.sh` runs clean
- [ ] `.env` contains the models you want to race
- [ ] Scoreboard loads at `http://localhost:3000`
- [ ] At least 2 full dry runs completed (to warm Claude prompt cache)
- [ ] Terminal font size is readable from the back of the room
- [ ] Backup screen recording of a successful run
