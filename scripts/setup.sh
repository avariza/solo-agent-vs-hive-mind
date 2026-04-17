#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT_DIR/.venv"

echo "========================================="
echo "  Hive Mind vs Solo Agent - Demo Setup"
echo "========================================="
echo ""

# Check prerequisites
echo "[1/6] Checking prerequisites..."
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js is required. Install from https://nodejs.org"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: Python 3 is required."; exit 1; }
command -v claude >/dev/null 2>&1 || { echo "ERROR: Claude Code is required. Run: npm install -g @anthropic-ai/claude-code"; exit 1; }

NODE_V=$(node --version)
PYTHON_V=$(python3 --version)
CLAUDE_V=$(claude --version 2>/dev/null || echo "unknown")
echo "  Node.js: $NODE_V"
echo "  Python:  $PYTHON_V"
echo "  Claude:  $CLAUDE_V"
echo ""

# Create virtual environment
echo "[2/6] Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  echo "  Created .venv"
else
  echo "  .venv already exists, reusing"
fi
source "$VENV_DIR/bin/activate"
echo "  Activated: $(which python)"
echo ""

# Install Python deps
echo "[3/6] Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install pytest pytest-cov pytest-json-report radon --quiet
echo "  pytest:           $(pytest --version 2>/dev/null | head -1)"
echo "  Done."
echo ""

# Install ruflo
echo "[4/6] Setting up ruflo..."
cd "$ROOT_DIR"
npx ruflo@latest init --wizard 2>/dev/null || npx ruflo@latest init
echo "  Done."
echo ""

# Install scoreboard deps
echo "[5/6] Installing scoreboard dependencies..."
cd "$ROOT_DIR/scoreboard"
npm install
echo "  Done."
echo ""

# Clean challenge workspaces
echo "[6/6] Cleaning challenge workspaces..."
rm -f "$ROOT_DIR/challenge/solo/src/rate_limiter.py"
rm -f "$ROOT_DIR/challenge/solo/src/test_rate_limiter.py"
rm -f "$ROOT_DIR/challenge/hive/src/rate_limiter.py"
rm -f "$ROOT_DIR/challenge/hive/src/test_rate_limiter.py"
touch "$ROOT_DIR/challenge/solo/src/__init__.py"
touch "$ROOT_DIR/challenge/hive/src/__init__.py"
echo "  Done."
echo ""

echo "========================================="
echo "  Setup complete!"
echo ""
echo "  To run the demo:"
echo "    source .venv/bin/activate"
echo "    cd scoreboard && node server.js &"
echo "    bash scripts/race.sh"
echo "========================================="
