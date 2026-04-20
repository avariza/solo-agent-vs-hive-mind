#!/bin/bash
# Clean all race artifacts between runs.
#
# Two flavours:
#   bash scripts/clean.sh            — normal clean (preserves ruflo memory,
#                                      so the hive retains cross-run learning
#                                      if you WANT the compounding narrative)
#   bash scripts/clean.sh --deep     — nukes ruflo memory AND workers state.
#                                      Use before a cold-start demo where
#                                      you need reproducible timings.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

DEEP=0
for arg in "$@"; do
  case "$arg" in
    --deep|-d) DEEP=1 ;;
  esac
done

echo "Cleaning challenge workspaces..."

# Solo side
rm -rf "$ROOT_DIR/challenge/solo/src/rate_limiter.py" \
       "$ROOT_DIR/challenge/solo/src/test_rate_limiter.py" \
       "$ROOT_DIR/challenge/solo/src/__pycache__" \
       "$ROOT_DIR/challenge/solo/.pytest_cache" \
       "$ROOT_DIR/challenge/solo/coverage.json" \
       "$ROOT_DIR/challenge/solo/.coverage" \
       "$ROOT_DIR/challenge/solo/test_results.json" \
       "$ROOT_DIR/challenge/solo/metrics.json"

# Hive side
rm -rf "$ROOT_DIR/challenge/hive/src/rate_limiter.py" \
       "$ROOT_DIR/challenge/hive/src/test_rate_limiter.py" \
       "$ROOT_DIR/challenge/hive/src/__pycache__" \
       "$ROOT_DIR/challenge/hive/.pytest_cache" \
       "$ROOT_DIR/challenge/hive/coverage.json" \
       "$ROOT_DIR/challenge/hive/.coverage" \
       "$ROOT_DIR/challenge/hive/test_results.json" \
       "$ROOT_DIR/challenge/hive/metrics.json" \
       "$ROOT_DIR/challenge/hive/.claude-flow" \
       "$ROOT_DIR/challenge/hive/.hive-mind"

# Legacy artifact (we no longer produce the handoff file).
rm -f "$ROOT_DIR/challenge/hive/ARCHITECT_HANDOFF.md"

# Scoreboard
rm -f "$ROOT_DIR/scoreboard/solo.log" \
      "$ROOT_DIR/scoreboard/hive.log" \
      "$ROOT_DIR/scoreboard/results.json" \
      "$ROOT_DIR/scoreboard/timing.json" \
      "$ROOT_DIR/scoreboard/start_time.txt" \
      "$ROOT_DIR/scoreboard/solo.ready" \
      "$ROOT_DIR/scoreboard/hive.ready" \
      "$ROOT_DIR/scoreboard/go.signal" \
      "$ROOT_DIR/scoreboard/solo.duration" \
      "$ROOT_DIR/scoreboard/hive.duration" \
      "$ROOT_DIR/scoreboard/solo.usage.json" \
      "$ROOT_DIR/scoreboard/hive.usage.json"

# Restore __init__.py
touch "$ROOT_DIR/challenge/solo/src/__init__.py"
touch "$ROOT_DIR/challenge/hive/src/__init__.py"

if [ "$DEEP" -eq 1 ]; then
  echo "--deep: nuking ruflo memory + learning state..."
  rm -rf "$ROOT_DIR/.claude-flow/data" \
         "$ROOT_DIR/.claude-flow/learning" \
         "$ROOT_DIR/.claude-flow/sessions" \
         "$ROOT_DIR/.claude-flow/metrics/learning.json"
  # Also clear the seeded RAG namespace so prep re-seeds from disk
  npx ruflo@latest memory delete --namespace "hive-gold" 2>&1 | tail -1 || true
fi

echo "Done. Ready to race$( [ "$DEEP" -eq 1 ] && echo " (deep-cleaned)")."
