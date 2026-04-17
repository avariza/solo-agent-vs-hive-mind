#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT_DIR/.venv"
SCOREBOARD_DIR="$ROOT_DIR/scoreboard"

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

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

# ---- PREP PHASE ----
{
  echo "========== [HIVE] PREP PHASE =========="
  echo "[HIVE] DEMO_MODE=$DEMO_MODE  (challenge: $(basename "$CHALLENGE_FILE"))"
  echo "[HIVE] Working in: $WORK_DIR"
  echo "[HIVE] Model: ${HIVE_MODEL:-<claude default>}"
  cd "$WORK_DIR"

  # Clean previous hive state
  rm -rf .claude-flow .hive-mind 2>/dev/null || true

  # Initialize hive-mind topology. This registers the coordination state
  # (hierarchical / raft consensus) that Claude Code picks up via hooks;
  # we no longer force a multi-phase prompt protocol — the hive's edge
  # over solo now comes from (a) the model selected via HIVE_MODEL and
  # (b) the coordination context provided by ruflo at runtime.
  echo "[HIVE] ruflo hive-mind init..."
  npx ruflo@latest hive-mind init \
    --topology hierarchical \
    --consensus raft \
    2>&1 || true

  echo "[HIVE] ruflo hive-mind spawn (4 workers)..."
  npx ruflo@latest hive-mind spawn \
    -n 4 \
    --queen-type tactical \
    --consensus weighted \
    2>&1 || true

  # Signal readiness
  touch "$READY_MARKER"
  echo "========== [HIVE] READY — WAITING FOR STARTING GUN =========="

  # Barrier: block until race.sh writes go.signal
  while [ ! -f "$GO_SIGNAL" ]; do
    sleep 0.1
  done

  START_OF_RACE=$(cat "$GO_SIGNAL")
  echo "========== [HIVE] GO! (t=$START_OF_RACE) =========="
} 2>&1 | tee -a "$LOG_FILE"

# ---- RACE PHASE ----
cd "$WORK_DIR"

START_OF_RACE=$(cat "$GO_SIGNAL")

# Both sides receive the same short prompt. What varies is the MODEL
# (SOLO_MODEL vs HIVE_MODEL) and the presence of the ruflo hive-mind
# coordination context initialized during prep.
HIVE_PROMPT="You are a senior Python developer. Complete this coding challenge in the current directory. The src/ directory and __init__.py already exist. Create the implementation and test files directly.

$CHALLENGE

After creating the files, run the tests:
pytest src/test_rate_limiter.py -v --tb=short --cov=src --cov-report=json --cov-report=term

IMPORTANT: Work only in the current directory. Do not create any other directories."

# Stream-json + parser: produces the usage summary (model, tokens, cost)
# at USAGE_FILE while still streaming readable text into the live log.
PYBIN="${PYTHON:-python3}"
if [ -x "$VENV_DIR/bin/python3" ]; then
  PYBIN="$VENV_DIR/bin/python3"
fi

# Optional --model arg, only set when HIVE_MODEL is non-empty.
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

END_OF_RACE=$(date +%s)
DURATION=$((END_OF_RACE - START_OF_RACE))
echo "$DURATION" > "$DURATION_FILE"

{
  echo ""
  echo "========== [HIVE] FINISHED in ${DURATION}s =========="
} | tee -a "$LOG_FILE"
