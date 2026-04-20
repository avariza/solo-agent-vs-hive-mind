# Hive Mind vs Solo Agent

**AI Tinkerers Montreal — April 2026 Demo**

A live, side-by-side race between two Claude Code agents solving the **same**
senior-level Python challenge. One side is a bare `claude -p` call. The other
is the same `claude -p` call wrapped in **ruflo**'s three headline capabilities:
RAG-seeded memory, a registered hive-mind topology, and a byzantine
self-review loop. The scoreboard is the referee.

The honest question we're answering on stage:

> **Does coordination scaffolding actually produce a better artifact, or does
> it just cost more tokens, more latency, and more complexity?**

Spoiler: the answer is "it depends, and the scoreboard will tell you which."

---

## The 90-second pitch

1. Both agents get the **same prompt**, the **same challenge file**, and fire
   off a **synchronized starting gun** (a barrier file written by
   `race.sh`).
2. The challenge is deliberately hard for a one-shot LLM: a weighted,
   thread-safe, sliding-window rate limiter with bounded memory, strict
   validation, and contention semantics. A 20-line stub gets maybe 1.5/5.
3. The scoreboard watches both working directories live via SSE, tails each
   agent's stream-json, and after both finish runs an **identical**
   evaluation pipeline against both artifacts: pytest, coverage, 8 hidden
   behavioral probes, radon complexity, and a multi-threaded throughput
   benchmark.
4. The audience sees tokens, dollars, and a 5-point score race in real
   time. No cherry-picking — the `results.json` is committed to the repo.

---

## What the audience sees vs. what's actually happening

The demo is intentionally a **split-screen race**, which is great theatre but
hides the most interesting engineering. This section is the "director's
commentary" — it's the part you should narrate on stage.

### On screen (left pane): 🧑 Solo Agent

- One `claude -p` call with a short prompt.
- No coordination, no retrieval, no review.
- This is the **baseline** — "how good is a modern frontier model when you
  just… ask it?"

### On screen (right pane): 🐝 Hive Mind

Same model, same challenge. But before the starting gun fires, `hive.sh`
does three things that look like log spam to the audience. They are not.

**(A) RAG seeding — ruflo + AgentDB**

Three curated reference files (`reference/rate_limiter_gold.py`,
`reference/edge_cases.md`, `reference/consensus_rubric.md`) are embedded
with ONNX vectors and stored in AgentDB under the `hive-gold` namespace:

```bash
npx ruflo memory store --key rate-limiter-golden-pattern --namespace hive-gold ...
npx ruflo memory store --key rate-limiter-edge-cases     --namespace hive-gold ...
npx ruflo memory store --key rate-limiter-consensus-rubric --namespace hive-gold ...
```

Inside the claude session, the hive agent **must** call the `memory_search`
MCP tool three times before writing code. The retrievals are genuine
semantic vector lookups — you can verify this by running
`npx ruflo memory search --query "thread-safe sliding window"` on its own.

**(B) Hive-mind topology — ruflo hive-mind**

```bash
npx ruflo hive-mind init  --topology hierarchical --consensus raft
npx ruflo hive-mind spawn -n 4 --queen-type tactical --consensus weighted
```

This registers a queen + 4 workers in ruflo's internal state with a raft
leader and weighted voting. It's a lightweight registration (we don't fan
out 4 separate `claude -p` sessions — that would blow the budget), but it's
what makes the post-race `ruflo hive-mind consensus` call at the end
legitimate: the consensus engine really is voting against a registered
topology.

**(C) Structured prompt — self-verification + byzantine review**

The hive prompt is longer than solo's **on purpose**. It mandates a
three-phase protocol:

1. **RAG retrieval** — the three `memory_search` calls above.
2. **Implementation + self-verification loop** — write the code, then run
   `pytest` and `scoreboard/metrics.py`, check against hard budgets
   (`max_cc ≤ 5`, `ops_per_sec ≥ 500k`, coverage `≥ 80%`), and loop up to
   3 times fixing the smallest thing that failed.
3. **3-voter byzantine self-review** — role-play a Performance Engineer,
   a Correctness Auditor, and a Security/Concurrency Reviewer against the
   retrieved consensus rubric. ≥2 must APPROVE or the agent does one
   revision round.

After the claude session exits, `ruflo hive-mind consensus --propose ...`
fires one more time as the "stamp of approval" from ruflo's distributed
decision subsystem. This one shows up in the live log panel so the
audience can see ruflo's consensus actually execute.

### Off screen: the scoring pipeline (both sides, identical)

This is the part that makes the comparison **fair**. After both agents
finish, `scripts/score.sh` runs the same four things against each
workspace:

| Check | What it actually does |
|---|---|
| `pytest --cov` | Runs the agent's own tests. Credit for pass rate + coverage. |
| `scoreboard/probes.py` | **8 hidden behavioral probes** the agent never sees: weighted cost accounting, sliding-window boundary, concurrent grants via `threading.Barrier`, stale-client eviction. Passing "all tests" is not enough. |
| `scoreboard/metrics.py` | Radon cyclomatic complexity + a real multi-threaded throughput benchmark (8 threads × 4000 ops). |
| `stream_parse.py` | Parses each side's `stream-json` into `solo.usage.json` / `hive.usage.json` — model, input/output/cache tokens, total cost USD, turns, wall-clock. |

The probes are why "write 3 lines and pass my own trivial test" can't win.
The contention benchmark is why lock granularity actually matters. The
cost tracking is why "just use Opus everywhere" is not the obvious answer.

---

## The scoring rubric (5 points, senior-dev weighted)

| Bucket | Max | How it's computed | Source |
|---|---|---|---|
| **Correctness** | **2.0** | `2 × min(test-pass-rate, probe-pass-rate)` | `pytest` + `scoreboard/probes.py` |
| **Deliverable** | **0.5** | `0.25` impl file exists + `0.25` test file exists | file checks |
| **Maintainability** | **1.0** | coverage bucket (≥80% → 0.6, ≥60% → 0.3) + `max_cc` bucket (≤5 → 0.4, ≤10 → 0.2) | `pytest-cov` + `radon` |
| **Performance** | **1.0** | `clamp01(log10(ops/50k)) × correctness` — 50k/s → 0, 500k/s → 1 (cap) | 8-thread ops/sec benchmark |
| **Conciseness** | **0.5** | `0.5 × concisenessRaw × correctness` — shorter impl/tests score higher | `lines_impl` + `lines_test` |
| **Total** | **5.0** | sum of the above | `scoreboard/evaluate.js` → `results.json` |
| Model / tokens / cost | display | advisory, not scored | `*.usage.json` |

Two design choices worth calling out on stage:

- **Correctness is half the budget.** Tests *and* the 8 hidden behavioral
  probes both have to pass to unlock the full 2.0 — and the `min(...)`
  gate means a suite that passes its own tests but misses probes still
  loses points. This is also what gates Performance and Conciseness, so
  "fast-but-wrong" and "short-but-wrong" both score zero.
- **Maintainability is a composite, not a single number.** Coverage
  answers *"did you test it?"*, `max_cc` answers *"is the hot path still
  simple?"*. Both contribute independently (max 0.6 + 0.4), so a
  100%-covered spaghetti implementation can't max the bucket.

### Which raw measurement feeds which bucket?

Each card on the live dashboard maps to exactly one rubric bucket, so
the audience can see how the raw numbers turn into the `/5` score:

| Dashboard card | Feeds bucket | Source |
|---|---|---|
| Impl File (Yes/No) | Deliverable (/0.5) | `has_implementation` |
| Test File (Yes/No) | Deliverable (/0.5) | `has_tests` |
| Tests Passing (x/y) | Correctness (/2) | `tests_passed / tests_total` |
| Edge Cases (x/y) | Correctness (/2) | `scoreboard/probes.py` |
| Coverage (%) | Maintainability (/1) | `pytest-cov` |
| Max Complexity | Maintainability (/1) | `radon cc` (via `metrics.py`) |
| Throughput (ops/s) | Performance (/1) | `scoreboard/metrics.py` |
| Code Lines | Conciseness (/0.5) | `lines_impl` |
| Test Lines | Conciseness (/0.5) | `lines_test` |
| Time / Model / Tokens / Cost | *advisory only* | `*.usage.json` |

---

## The counter-intuitive result (and why we kept it)

Here's the last committed run (`scoreboard/results.json`, Solo on
`claude-opus-4-6`, Hive on `claude-haiku-4-5`):

| | Solo | Hive |
|---|---|---|
| **Score** | 3.2 / 5 | **4.68 / 5** |
| Tests passed | 20/20 | 23/23 |
| Coverage | 100% | 97.01% |
| Probes passed | 6/8 | 8/8 |
| `max_cc` | 7 | 6 |
| Throughput (ops/sec) | 60,990 | **1,237,331** |
| p99 latency | 4,504 µs | **0.92 µs** |
| Impl / test lines | 45 / 209 | 85 / 182 |
| Cost | $0.196 | **$0.099** |
| Duration | 50 s | 71 s |

Same challenge, same scoring pipeline, **different trade-off**. Hive wins
even though its model (Haiku) is ~15× cheaper than Solo's (Opus). Why?

Solo's implementation is slightly tighter (fewer lines, 100% coverage)
but misses **2 of the 8 hidden probes**. Under the new rubric,
`min(test-pass-rate, probe-pass-rate) = 6/8 = 0.75` gates *all* its
downstream buckets: correctness caps at 1.5/2, and performance —
despite being a real throughput number — gets multiplied by 0.75. The
hive's scaffolding (the RAG seed + the 3-voter self-review) is exactly
what pushes probe coverage from 6/8 → 8/8, which then unlocks the full
performance bucket (its 1.2M ops/sec blows past the 500k cap).

The flip side: on a **different run with different prompts**, Solo with a
global `threading.Lock` has beaten Hive's per-client locks by 20× on
throughput. **More coordination ≠ better code, especially when the
problem is small and the model is strong** — but coordination *does* earn
its keep when correctness is underspecified, because that's what the
probes measure. The scoreboard will show you which side of that trade-off
you're on every time you change `.env`.

Tell the audience to try these configurations:

| `SOLO_MODEL` | `HIVE_MODEL` | The question you're asking |
|---|---|---|
| `haiku` | `opus` | Is Opus worth ~15× Haiku's cost on a well-specified task? |
| `sonnet` | `sonnet` | Pure coordination-overhead isolation — what does ruflo buy a good model? |
| `haiku` | `haiku` | Can scaffolding lift a cheap model into frontier territory? |
| `opus` | `haiku` | Reversed — can Haiku-in-a-hive beat Opus-solo? |

---

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

### Model selection (`.env`)

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

---

## How the starting gun works (for the curious)

Each side is a background bash process that does its prep phase, writes a
`.ready` marker file, and then **polls** for a `go.signal` file. `race.sh`
waits until both `.ready` markers exist, counts down 3-2-1, and writes a
single shared timestamp into `go.signal`. Both processes unblock within
~100ms of each other and start their `claude -p` call.

Durations are recorded per-side into `solo.duration` / `hive.duration`
from inside each script, so the scoreboard's elapsed counter reflects
**race time**, not prep time. Prep is free — that's the whole point of
setting it up in advance.

---

## Project structure

```
├── .env                          # SOLO_MODEL / HIVE_MODEL
├── challenge/
│   ├── CHALLENGE.md              # The identical prompt both sides receive
│   ├── CHALLENGE_FAST.md         # Trimmed variant for DEMO_MODE=fast
│   ├── solo/                     # Solo agent workspace (src/ pre-created)
│   └── hive/                     # Hive mind workspace (src/ pre-created)
├── reference/                    # Seeded into AgentDB for the hive only
│   ├── rate_limiter_gold.py      # Golden-pattern implementation
│   ├── edge_cases.md             # Probe/edge-case playbook
│   └── consensus_rubric.md       # 3-voter review rubric
├── scoreboard/
│   ├── server.js                 # SSE server watching both workspaces
│   ├── index.html                # Live dashboard
│   ├── evaluate.js               # Post-race scoring
│   ├── probes.py                 # 8 hidden behavioral probes
│   ├── metrics.py                # radon complexity + threaded throughput
│   ├── solo.usage.json           # Per-side token/cost summary (generated)
│   ├── hive.usage.json           # ditto
│   └── results.json              # Final score output (committed)
├── scripts/
│   ├── setup.sh                  # One-time install
│   ├── race.sh                   # Clean, launch both, synchronized start, score
│   ├── solo.sh                   # Solo launcher (reads SOLO_MODEL)
│   ├── hive.sh                   # Hive launcher (ruflo memory + hive-mind + HIVE_MODEL)
│   ├── score.sh                  # Re-score an already-completed run
│   ├── clean.sh                  # Nuke all race artifacts
│   └── stream_parse.py           # Parses claude stream-json → usage summary
└── README.md
```

---

## Prerequisites

- Node.js 20+
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- ruflo (auto-installed by `setup.sh`)

## Demo-day checklist

- [ ] `bash scripts/setup.sh` runs clean
- [ ] `.env` contains the models you want to race
- [ ] Scoreboard loads at `http://localhost:3000`
- [ ] At least 2 full dry runs completed (warms Claude prompt cache —
      noticeable cost drop on run 2+)
- [ ] `ls reference/` shows all three files (RAG seeding fails silently
      otherwise)
- [ ] `npx ruflo memory search --query test` responds without errors
- [ ] Terminal font size is readable from the back of the room
- [ ] Backup screen recording of a successful run on USB

---

## Talking points (cheat sheet)

- **"The comparison is fair because the scoring is identical."** Point
  at `scripts/score.sh` — one file, runs the same pipeline on both
  workspaces.
- **"The hidden probes are why 'all tests pass' doesn't mean what you
  think."** Show `scoreboard/probes.py` — the agents never see it.
- **"The hive gets three ruflo capabilities, not just a longer prompt."**
  Narrate the RAG seed, the topology registration, and the post-race
  consensus call as they scroll past in the log.
- **"More scaffolding can lose on a small, well-specified task."** Show
  the 20× throughput gap in the committed `results.json` and explain why.
- **"Change one line in `.env` and the answer flips."** End on this.
  Invite the audience to run it themselves.
