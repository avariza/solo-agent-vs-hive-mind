#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT_DIR/.venv"
SCOREBOARD_DIR="$ROOT_DIR/scoreboard"
REFERENCE_DIR="$ROOT_DIR/reference"

# Load SOLO_MODEL / HIVE_MODEL (and any other overrides) from .env.
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

# DEMO_MODE: "full" (default) or "fast" — fast mode uses the trimmed
# challenge spec and ~6 probes so the race completes in ~90s instead of ~5min.
DEMO_MODE="${DEMO_MODE:-full}"
if [ "$DEMO_MODE" = "fast" ]; then
  CHALLENGE_FILE="$ROOT_DIR/challenge/CHALLENGE_FAST.md"
else
  CHALLENGE_FILE="$ROOT_DIR/challenge/CHALLENGE.md"
fi
CHALLENGE=$(cat "$CHALLENGE_FILE")

WORK_DIR="$ROOT_DIR/challenge/hive"
LOG_FILE="$SCOREBOARD_DIR/hive.log"

READY_MARKER="$SCOREBOARD_DIR/hive.ready"
GO_SIGNAL="$SCOREBOARD_DIR/go.signal"
DURATION_FILE="$SCOREBOARD_DIR/hive.duration"
USAGE_FILE="$SCOREBOARD_DIR/hive.usage.json"
STREAM_PARSE="$SCRIPT_DIR/stream_parse.py"

# Namespace we seed with golden patterns so the hive can RAG-retrieve
# them at runtime via the `memory_search` MCP tool. The same namespace
# is cleared by scripts/clean.sh so runs don't leak into each other
# (unless you want them to — see the preflight doc).
MEMORY_NS="hive-gold"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

# ---- PREP PHASE ----
# All three ruflo superpowers are wired in here:
#   (A) RAG — three curated patterns stored in AgentDB, searchable via
#       the ruflo MCP server from inside the claude session
#   (B) Hive-mind topology registered (queen + 4 workers, raft consensus)
#   (C) The claude prompt itself embeds self-verification + 3-voter
#       byzantine review, plus a post-race `hive-mind consensus` call
{
  echo "========== [HIVE] PREP PHASE =========="
  echo "[HIVE] DEMO_MODE=$DEMO_MODE  (challenge: $(basename "$CHALLENGE_FILE"))"
  echo "[HIVE] Working in: $WORK_DIR"
  echo "[HIVE] Model: ${HIVE_MODEL:-<claude default>}"
  cd "$WORK_DIR"

  # Clean previous hive state
  rm -rf .claude-flow .hive-mind 2>/dev/null || true

  # ---- (A) RAG SEEDING ----
  echo ""
  echo "[HIVE] ruflo memory store — seeding 3 curated patterns to namespace '$MEMORY_NS'..."

  # Clear stale entries from previous runs so retrievals are deterministic.
  npx ruflo@latest memory delete --namespace "$MEMORY_NS" 2>&1 || true

  # Pattern 1: the throughput-optimal rate limiter shape
  npx ruflo@latest memory store \
    --key "rate-limiter-golden-pattern" \
    --value "$(cat "$REFERENCE_DIR/rate_limiter_gold.py")" \
    --namespace "$MEMORY_NS" 2>&1 || true

  # Pattern 2: the probe/edge-case playbook
  npx ruflo@latest memory store \
    --key "rate-limiter-edge-cases" \
    --value "$(cat "$REFERENCE_DIR/edge_cases.md")" \
    --namespace "$MEMORY_NS" 2>&1 || true

  # Pattern 3: the 3-voter consensus rubric
  npx ruflo@latest memory store \
    --key "rate-limiter-consensus-rubric" \
    --value "$(cat "$REFERENCE_DIR/consensus_rubric.md")" \
    --namespace "$MEMORY_NS" 2>&1 || true

  # ---- (B) HIVE-MIND TOPOLOGY ----
  echo ""
  echo "[HIVE] ruflo hive-mind init (hierarchical + raft)..."
  npx ruflo@latest hive-mind init \
    --topology hierarchical \
    --consensus raft \
    2>&1 || true

  echo "[HIVE] ruflo hive-mind spawn (4 workers, tactical queen)..."
  # The --count flag is the canonical name in current ruflo; the legacy
  # -n flag was being interpreted as a positional index, spawning just 1.
  npx ruflo@latest hive-mind spawn \
    --count 4 \
    --queen-type tactical \
    --consensus weighted \
    2>&1 || true

  # Signal readiness
  touch "$READY_MARKER"
  echo "========== [HIVE] READY — WAITING FOR STARTING GUN =========="

  while [ ! -f "$GO_SIGNAL" ]; do
    sleep 0.1
  done

  START_OF_RACE=$(cat "$GO_SIGNAL")
  echo "========== [HIVE] GO! (t=$START_OF_RACE) =========="
} 2>&1 | tee -a "$LOG_FILE"

# ---- RACE PHASE ----
cd "$WORK_DIR"

START_OF_RACE=$(cat "$GO_SIGNAL")

# Structured prompt with three explicit phases the hive must execute:
#   1. RAG retrieval — pull seeded patterns from AgentDB before coding
#   2. Implementation + self-verification loop against scoreboard/metrics.py
#   3. Three-voter byzantine review (perf / correctness / security) with
#      iteration on any REJECT
#
# The prompt is longer than solo's by design — the hive IS getting extra
# scaffolding. That's exactly the thing we're measuring: does spending
# more prompt + more tokens on coordination produce a better artifact?
HIVE_PROMPT="You coordinate a hive-mind swarm on a Python challenge. Be terse — every extra word is wasted latency.

cwd = challenge/hive. \`src/__init__.py\` exists. Produce \`src/rate_limiter.py\` + \`src/test_rate_limiter.py\`.

== CHALLENGE ==
$CHALLENGE

== PROTOCOL (3 phases, minimal prose) ==

PHASE 1 — RAG (one attempt, then fall through):
Try \`memory_search\` MCP tool once: query='rate limiter golden pattern' namespace='$MEMORY_NS'.
If the tool isn't immediately available OR returns nothing, read these files directly and move on — do NOT retry:
  ../../reference/rate_limiter_gold.py
  ../../reference/edge_cases.md
  ../../reference/consensus_rubric.md
Adopt the golden pattern's shape; do not copy the teaching docstring.

PHASE 2 — IMPLEMENT + SELF-VERIFY:
Budgets (hard): impl <= 85 lines, max_cc <= 5, single global Lock, O(1) hot path (deque.popleft + incremental used counter), full API (\`allow_request\`, \`time_until_allowed\`, \`snapshot\`).
Write impl + tests in one pass (tests: 15-22, cover every edge_cases.md item, 150-220 lines).
Then loop ≤2 iterations:
  1. \`pytest src/test_rate_limiter.py --tb=line --cov=src --cov-report=json\`
  2. \`python ../../scoreboard/metrics.py . metrics.json\` then read metrics.json
  3. Gate: 100% pass, coverage>=80%, ops_per_sec>=500000, max_cc<=5. Fix the smallest thing on fail. If still failing after iter 2, ship.

PHASE 3 — BYZANTINE REVIEW (strict output format, one line per voter, TOTAL ≤ 60 words):
V1 perf: APPROVE|REJECT — <≤12 words on ops_per_sec + hot-path>
V2 correctness: APPROVE|REJECT — <≤12 words on tests + boundary + bool>
V3 concurrency: APPROVE|REJECT — <≤12 words on lock + monotonic + memory>
If ≥1 REJECT with a concrete fix, apply it, re-run metrics, re-vote once. Then stop.

Hard rules:
- Do not read scoreboard/probes.py.
- Do not narrate what you are about to do. Just do it.
- Final message: the 3 voter lines + one word (\"APPROVED\" or \"SHIPPED_WITH_REJECTS\"). Nothing else."

# Stream-json + parser: produces the usage summary (model, tokens, cost)
# at USAGE_FILE while still streaming readable text into the live log.
PYBIN="${PYTHON:-python3}"
if [ -x "$VENV_DIR/bin/python3" ]; then
  PYBIN="$VENV_DIR/bin/python3"
fi

MODEL_ARGS=()
if [ -n "${HIVE_MODEL:-}" ]; then
  MODEL_ARGS+=(--model "$HIVE_MODEL")
fi

echo "[HIVE] Launching Claude Code (model=${HIVE_MODEL:-default})..." | tee -a "$LOG_FILE"
claude -p "$HIVE_PROMPT" \
  "${MODEL_ARGS[@]}" \
  --output-format stream-json \
  --verbose \
  --dangerously-skip-permissions \
  2>&1 \
  | "$PYBIN" -u "$STREAM_PARSE" "$USAGE_FILE" \
  | tee -a "$LOG_FILE"

# Stop the clock HERE — the challenge is done. Anything below this line
# (post-race ruflo consensus stamp, etc.) is scoring/ceremony, not racing,
# and must not penalize the hive's duration vs solo.
END_OF_RACE=$(date +%s)
DURATION=$((END_OF_RACE - START_OF_RACE))
echo "$DURATION" > "$DURATION_FILE"

# ---- POST-RACE: RUFLO HIVE-MIND CONSENSUS ON THE FINAL ARTIFACT ----
# This is the externally-visible ruflo consensus call. The internal 3-voter
# review happened inside the claude session; this one is the "stamp of
# approval" from ruflo's own consensus engine and shows up in the log so
# the audience sees ruflo's distributed-decision subsystem actually fire.
# Intentionally runs AFTER the duration file is written so it doesn't
# inflate the race time.
{
  echo ""
  echo "========== [HIVE] POST-RACE: ruflo hive-mind consensus =========="
  IMPL_PATH="$WORK_DIR/src/rate_limiter.py"
  if [ -f "$IMPL_PATH" ]; then
    PROPOSAL="Approve final rate_limiter.py: $(wc -l < "$IMPL_PATH" | tr -d ' ') lines, implements full API, self-verified against metrics.py"
    npx ruflo@latest hive-mind consensus \
      --propose "$PROPOSAL" \
      2>&1 || echo "[HIVE] consensus call completed (or not supported in this ruflo build — non-fatal)"
  else
    echo "[HIVE] no implementation produced; skipping consensus vote"
  fi
} | tee -a "$LOG_FILE"

{
  echo ""
  echo "========== [HIVE] FINISHED in ${DURATION}s =========="
} | tee -a "$LOG_FILE"
