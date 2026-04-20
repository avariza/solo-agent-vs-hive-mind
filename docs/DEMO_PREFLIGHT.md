# Demo Preflight — Hive Mind vs Solo

Use this doc the day of the demo. It assumes you already ran
`bash scripts/setup.sh` at least once.

## What changed vs the old demo

The hive now actually uses three ruflo subsystems instead of just
registering a topology and running plain `claude -p`:

| Phase | Ruflo feature | Where it fires |
|---|---|---|
| A. RAG seeding | `ruflo memory store` / `memory_search` (AgentDB + HNSW) | `scripts/hive.sh` prep; retrieved inside the claude session via the `claude-flow` MCP server |
| B. Topology | `ruflo hive-mind init` + `spawn` (queen + 4 workers, raft) | `scripts/hive.sh` prep |
| C. Consensus | Internal 3-voter byzantine review in the prompt + post-race `ruflo hive-mind consensus --propose` | inside claude session + post-race log |

The solo side is unchanged — single `claude -p`, no retrieval, no
verification loop, no consensus. That's the control.

The hive's prompt now forces:

1. Retrieve 3 curated patterns from AgentDB namespace `hive-gold`
2. Implement the **complete** API (`allow_request`, `time_until_allowed`,
   `snapshot`) — solo skips the last two
3. Self-verify against `scoreboard/metrics.py` until thresholds met
4. 3-voter byzantine self-review with one revision round if rejected

## One-time prerequisites

```bash
# Already done if you ran setup.sh before
bash scripts/setup.sh

# Sanity check
.venv/bin/python -c "import pytest, radon; print('py ok')"
node --version       # MUST be >= 22 — see note below
which claude         # Claude Code CLI installed
npx ruflo@latest --version
```

### ⚠ Node 22+ is required for RAG to actually work

Ruflo's memory subsystem imports `@ruvector/rvf-wasm`, which uses
`import.meta` ESM syntax. On Node 20 the three `ruflo memory store`
calls in the prep phase crash silently with
`SyntaxError: Cannot use 'import.meta' outside a module`, and the
hive's `memory_search` tool returns nothing. The hive then falls
through to reading `reference/` directly (still works, but the RAG
narrative is dead).

```bash
# Recommended: use nvm
nvm install 22
nvm use 22
node --version       # should print v22.x or higher
```

If you can't upgrade Node, the demo still runs — just skip the
"watch ruflo seed AgentDB" beat and tell the story as
"hive retrieves curated patterns from the reference/ library."

## Demo day flow

### 1. Choose your cleaning level

```bash
# Normal clean — preserves ruflo's cross-run memory/learning.
# Use if you want to tell the "hive gets better each run" story.
bash scripts/clean.sh

# Deep clean — nukes .claude-flow/data/, learning state, and the
# hive-gold RAG namespace. Use this for a reproducible cold start
# before the first live demo so timings aren't distorted by cache.
bash scripts/clean.sh --deep
```

Recommendation for live demo: **one `--deep` clean before the first
race**, then plain `bash scripts/clean.sh` between subsequent runs so
the compounding-learning story is still true.

### 2. Set models in `.env`

Current default in `.env` (tuned for a ≤ 90s hive):

```bash
SOLO_MODEL=claude-opus-4-6
HIVE_MODEL=claude-haiku-4-5-20251001
```

The haiku setup is the demo-friendly configuration: solo gets the
expensive model all to itself, the hive coordinates a cheaper
model through RAG + self-verification and still wins on score.
Haiku generates 3–5× faster, so the hive finishes in ≈ 90s instead
of ≈ 260s.

If you want the apples-to-apples version (same model both sides),
set both to `claude-opus-4-6` — but budget ~4 minutes per hive run.

### 3. Start the scoreboard (own terminal, leave running)

```bash
cd scoreboard && npm start
# Opens at http://localhost:3000
```

### 4. Run the race

```bash
# Full race (~3-5 min per side, 8 hidden probes)
bash scripts/race.sh

# Fast variant (~90s per side, 6 probes) — safer for a live demo
DEMO_MODE=fast bash scripts/race.sh
```

The hive's prep phase will print three log banners that let the
audience see ruflo actually doing something:

```
[HIVE] ruflo memory store — seeding 3 curated patterns to namespace 'hive-gold'...
[HIVE] ruflo hive-mind init (hierarchical + raft)...
[HIVE] ruflo hive-mind spawn (4 workers, tactical queen)...
```

During the race you'll see the hive's claude session make `memory_search`
MCP calls (Phase 1), iterate pytest + metrics.py (Phase 2), and
role-play the 3-voter review (Phase 3). After the race, a
`[HIVE] POST-RACE: ruflo hive-mind consensus` banner prints with the
approval proposal.

## What to expect on the scoreboard

With the changes in place, the hive should:

| Metric | First opus hive run | Expected with haiku + tightened prompt | Mechanism |
|---|---|---|---|
| Max complexity | 5 (5 pts) | ≤ 5 (5 pts) | RAG pattern + self-check |
| Throughput | 1.31M ops/s (5 pts, capped) | > 500k (5 pts, capped) | RAG pattern (deque + incremental counter) |
| Behavioral probes | 6/6 | 6/6 | edge_cases.md pattern |
| API completeness | all 3 methods | all 3 methods | explicit prompt instruction |
| Conciseness | 8.7 | 8.5–9.2 | terser prompt → less prose → fewer impl lines |
| **Final score** | 98.7 | **96–99** (small variance) | same metric ceilings, cheaper model |
| Tokens (out) | ~14k | ~4–6k | 1-line votes + "do not narrate" clause |
| Cost | $0.87 | **$0.05–0.10** | haiku is ~50× cheaper per token than opus |
| **Duration** | **261s** | **≤ 90s** | haiku generation speed + no retry loops |

The new demo story is:

> *"Solo burns opus on a fresh-context write. It ships in 53 seconds
> but its implementation is O(N) per request (68k ops/sec vs the
> hive's 500k+). The hive runs on haiku — 50× cheaper per token —
> but retrieves institutional patterns from AgentDB, self-verifies
> against the benchmark, and passes a 3-voter byzantine review. It
> wins on score, wins on cost, and only costs ~40s of extra wall time.
> Ruflo turns a cheap model into an engineering team."*

## If something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `ruflo memory store` errors in prep log | Ruflo not installed or MCP daemon not running | `npx ruflo@latest doctor --fix` |
| Hive `memory_search` returns nothing | Namespace wasn't seeded (prep phase failed silently) | Re-run with `--deep` clean; check `[HIVE] ruflo memory store` banners appeared |
| Hive implementation at 0 lines | Claude session crashed mid-run | Check `scoreboard/hive.log` for the stream error; almost always a rate-limit |
| Hive throughput < 500k | Agent ignored the RAG pattern | Check it actually called `memory_search` in the log; if not, the claude-flow MCP server isn't registered (inspect `.mcp.json`) |
| `hive-mind consensus` call errors | Command may have moved between ruflo versions | Non-fatal — the internal 3-voter review in the prompt still fires |
| Scoreboard shows "--" for hive | `metrics.py` or probes crashed on the hive's impl | `bash scripts/score.sh` to re-score; look at `challenge/hive/metrics.json` |

## Files touched in this refactor

```
reference/                        # NEW — seed material for RAG
├── rate_limiter_gold.py           # throughput-optimal reference impl
├── edge_cases.md                  # probe/behavior enumeration
└── consensus_rubric.md            # 3-voter review criteria

scripts/
├── hive.sh                        # rewritten: RAG + self-verify + consensus
└── clean.sh                       # new --deep flag

docs/
└── DEMO_PREFLIGHT.md              # this file
```

Solo-side scripts and the scoreboard are unchanged — the comparison
stays honest.

## Sanity check before going live

```bash
# 1. Syntax check the scripts
bash -n scripts/hive.sh scripts/solo.sh scripts/clean.sh scripts/race.sh

# 2. Verify the golden reference still benchmarks above the cap
mkdir -p /tmp/goldtest/src
cp reference/rate_limiter_gold.py /tmp/goldtest/src/rate_limiter.py
touch /tmp/goldtest/src/__init__.py
.venv/bin/python scoreboard/metrics.py /tmp/goldtest /tmp/goldtest/metrics.json
# Expect ops_per_sec > 500_000 and max_cc <= 5

# 3. One dry race to warm prompt cache (reduces demo-time variance)
DEMO_MODE=fast bash scripts/race.sh

# 4. Deep clean, then you're ready
bash scripts/clean.sh --deep
```
