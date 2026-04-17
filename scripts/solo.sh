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

DEMO_MODE="${DEMO_MODE:-full}"
if [ "$DEMO_MODE" = "fast" ]; then
  CHALLENGE_FILE="$ROOT_DIR/challenge/CHALLENGE_FAST.md"
else
  CHALLENGE_FILE="$ROOT_DIR/challenge/CHALLENGE.md"
fi
CHALLENGE=$(cat "$CHALLENGE_FILE")
WORK_DIR="$ROOT_DIR/challenge/solo"
LOG_FILE="$SCOREBOARD_DIR/solo.log"

READY_MARKER="$SCOREBOARD_DIR/solo.ready"
GO_SIGNAL="$SCOREBOARD_DIR/go.signal"
DURATION_FILE="$SCOREBOARD_DIR/solo.duration"
USAGE_FILE="$SCOREBOARD_DIR/solo.usage.json"
STREAM_PARSE="$SCRIPT_DIR/stream_parse.py"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

# Everything in this script streams into solo.log so the scoreboard
# terminal panel shows prep + race activity continuously.
{
  echo "========== [SOLO] PREP PHASE =========="
  echo "[SOLO] DEMO_MODE=$DEMO_MODE  (challenge: $(basename "$CHALLENGE_FILE"))"
  echo "[SOLO] Working in: $WORK_DIR"
  echo "[SOLO] Model: ${SOLO_MODEL:-<claude default>}"
  echo "[SOLO] No prep required — agent is a single claude -p invocation."
  cd "$WORK_DIR"

  # Signal readiness to the race orchestrator
  touch "$READY_MARKER"
  echo "========== [SOLO] READY — WAITING FOR STARTING GUN =========="

  # Barrier: block until race.sh writes go.signal
  while [ ! -f "$GO_SIGNAL" ]; do
    sleep 0.1
  done

  START_OF_RACE=$(cat "$GO_SIGNAL")
  echo "========== [SOLO] GO! (t=$START_OF_RACE) =========="
} 2>&1 | tee -a "$LOG_FILE"

# Note: we must exit the tee'd subshell before running claude,
# so claude output is piped directly into tee from this point on.
START_OF_RACE=$(cat "$GO_SIGNAL")

cd "$WORK_DIR"

# Stream-json gives us per-event metadata (model, usage, cost). We pipe it
# through stream_parse.py which:
#   - emits human-readable text on stdout (tee'd to the live log panel)
#   - writes a usage summary JSON to USAGE_FILE for evaluate.js
PYBIN="${PYTHON:-python3}"
if [ -x "$VENV_DIR/bin/python3" ]; then
  PYBIN="$VENV_DIR/bin/python3"
fi

# Optional --model arg, only set when SOLO_MODEL is non-empty.
MODEL_ARGS=()
if [ -n "${SOLO_MODEL:-}" ]; then
  MODEL_ARGS+=(--model "$SOLO_MODEL")
fi

echo "[SOLO] Launching Claude Code (model=${SOLO_MODEL:-default})..." | tee -a "$LOG_FILE"
claude -p "You are a senior Python developer. Complete this coding challenge in the current directory. The src/ directory and __init__.py already exist. Create the implementation and test files directly.

$CHALLENGE

After creating the files, run the tests:
pytest src/test_rate_limiter.py -v --tb=short --cov=src --cov-report=json --cov-report=term

IMPORTANT: Work only in the current directory. Do not create any other directories." \
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
  echo "========== [SOLO] FINISHED in ${DURATION}s =========="
} | tee -a "$LOG_FILE"
