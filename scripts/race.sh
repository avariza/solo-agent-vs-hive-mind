#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT_DIR/.venv"
SCOREBOARD_DIR="$ROOT_DIR/scoreboard"

SOLO_READY="$SCOREBOARD_DIR/solo.ready"
HIVE_READY="$SCOREBOARD_DIR/hive.ready"
GO_SIGNAL="$SCOREBOARD_DIR/go.signal"
SOLO_DURATION_FILE="$SCOREBOARD_DIR/solo.duration"
HIVE_DURATION_FILE="$SCOREBOARD_DIR/hive.duration"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🏁  HIVE MIND vs SOLO AGENT  🏁           ║"
echo "║   AI Tinkerers Montreal - April 2026         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Clean previous results (including barrier/signal/duration files)
rm -f "$ROOT_DIR/challenge/solo/src/rate_limiter.py"
rm -f "$ROOT_DIR/challenge/solo/src/test_rate_limiter.py"
rm -f "$ROOT_DIR/challenge/hive/src/rate_limiter.py"
rm -f "$ROOT_DIR/challenge/hive/src/test_rate_limiter.py"
rm -f "$ROOT_DIR/challenge/solo/coverage.json"
rm -f "$ROOT_DIR/challenge/hive/coverage.json"
rm -f "$ROOT_DIR/challenge/solo/test_results.json"
rm -f "$ROOT_DIR/challenge/hive/test_results.json"
rm -f "$SCOREBOARD_DIR/solo.log"
rm -f "$SCOREBOARD_DIR/hive.log"
rm -f "$SCOREBOARD_DIR/results.json"
rm -f "$SCOREBOARD_DIR/timing.json"
rm -f "$SCOREBOARD_DIR/start_time.txt"
rm -f "$SOLO_READY" "$HIVE_READY" "$GO_SIGNAL"
rm -f "$SOLO_DURATION_FILE" "$HIVE_DURATION_FILE"

touch "$ROOT_DIR/challenge/solo/src/__init__.py"
touch "$ROOT_DIR/challenge/hive/src/__init__.py"

echo "Challenge: Sliding Window Rate Limiter (Python)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  LEFT:  🧑 Solo Claude Code agent"
echo "  RIGHT: 🐝 Ruflo Hive Mind (Queen + 4 workers)"
echo ""
echo "Launching both sides (prep phase)..."
echo ""

# Launch both scripts in background — each does its prep, writes a .ready
# marker, then blocks on the barrier waiting for go.signal.
bash "$SCRIPT_DIR/solo.sh" &
SOLO_PID=$!

bash "$SCRIPT_DIR/hive.sh" &
HIVE_PID=$!

echo "Solo PID=$SOLO_PID | Hive PID=$HIVE_PID"
echo "Open the scoreboard: http://localhost:3000"
echo ""
echo "Waiting for both sides to finish prep..."

# Barrier: wait until both ready markers exist, OR either process dies early.
while true; do
  SOLO_IS_READY=0 ; [ -f "$SOLO_READY" ] && SOLO_IS_READY=1
  HIVE_IS_READY=0 ; [ -f "$HIVE_READY" ] && HIVE_IS_READY=1

  if [ $SOLO_IS_READY -eq 1 ] && [ $HIVE_IS_READY -eq 1 ]; then
    break
  fi

  if ! kill -0 $SOLO_PID 2>/dev/null && [ $SOLO_IS_READY -eq 0 ]; then
    echo "[ERROR] Solo process exited before signaling ready. Aborting."
    kill $HIVE_PID 2>/dev/null || true
    wait $HIVE_PID 2>/dev/null || true
    exit 1
  fi
  if ! kill -0 $HIVE_PID 2>/dev/null && [ $HIVE_IS_READY -eq 0 ]; then
    echo "[ERROR] Hive process exited before signaling ready. Aborting."
    kill $SOLO_PID 2>/dev/null || true
    wait $SOLO_PID 2>/dev/null || true
    exit 1
  fi

  sleep 0.2
done

echo "Both sides ready. Firing starting gun in 3..."
sleep 1
echo "2..."
sleep 1
echo "1..."
sleep 1

# Synchronized start: write the go signal with a single shared timestamp.
# Both scripts are polling for this file and will unblock within ~100ms of
# each other. start_time.txt is what the scoreboard server uses to compute
# the live elapsed counter, so it now reflects race time (not prep time).
START_TIME=$(date +%s)
echo "$START_TIME" > "$SCOREBOARD_DIR/start_time.txt"
echo "$START_TIME" > "$GO_SIGNAL"

echo "GO! 🚀 (t=$START_TIME)"
echo ""

# Wait for both to finish. Per-side durations are written by each script
# into its own .duration file so we don't have to worry about which one
# finishes first.
SOLO_EXIT=0
HIVE_EXIT=0

wait $SOLO_PID || SOLO_EXIT=$?
echo ""
echo "[SOLO] Process exited with code $SOLO_EXIT"

wait $HIVE_PID || HIVE_EXIT=$?
echo ""
echo "[HIVE] Process exited with code $HIVE_EXIT"

# Read per-side durations (fall back to wall-clock from START_TIME if missing)
SOLO_DURATION=0
HIVE_DURATION=0
if [ -f "$SOLO_DURATION_FILE" ]; then
  SOLO_DURATION=$(cat "$SOLO_DURATION_FILE")
fi
if [ -f "$HIVE_DURATION_FILE" ]; then
  HIVE_DURATION=$(cat "$HIVE_DURATION_FILE")
fi

if [ "$SOLO_DURATION" = "0" ] || [ -z "$SOLO_DURATION" ]; then
  SOLO_DURATION=$(($(date +%s) - START_TIME))
fi
if [ "$HIVE_DURATION" = "0" ] || [ -z "$HIVE_DURATION" ]; then
  HIVE_DURATION=$(($(date +%s) - START_TIME))
fi

echo "{\"solo_seconds\": $SOLO_DURATION, \"hive_seconds\": $HIVE_DURATION}" > "$SCOREBOARD_DIR/timing.json"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Both sides done. Running evaluation..."
echo ""

# Run evaluation
bash "$SCRIPT_DIR/score.sh"
