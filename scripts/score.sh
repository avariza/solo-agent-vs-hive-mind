#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT_DIR/.venv"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d "$VENV_DIR" ]; then
  source "$VENV_DIR/bin/activate"
fi

echo "╔══════════════════════════════════════════════╗"
echo "║            📊  EVALUATION  📊               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Run tests for solo side
echo "[SOLO] Running tests..."
cd "$ROOT_DIR/challenge/solo"
if [ -f "src/rate_limiter.py" ] && [ -f "src/test_rate_limiter.py" ]; then
  pytest src/test_rate_limiter.py -v --tb=short \
    --cov=src --cov-report=json --cov-report=term \
    --json-report --json-report-file=test_results.json \
    2>&1 || true
  echo ""
else
  echo "  WARNING: Source files missing!"
  echo ""
fi

# Run tests for hive side
echo "[HIVE] Running tests..."
cd "$ROOT_DIR/challenge/hive"
if [ -f "src/rate_limiter.py" ] && [ -f "src/test_rate_limiter.py" ]; then
  pytest src/test_rate_limiter.py -v --tb=short \
    --cov=src --cov-report=json --cov-report=term \
    --json-report --json-report-file=test_results.json \
    2>&1 || true
  echo ""
else
  echo "  WARNING: Source files missing!"
  echo ""
fi

# Run the Node.js evaluator for final scoring
cd "$ROOT_DIR"
node scoreboard/evaluate.js
