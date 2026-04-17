#!/usr/bin/env python3
"""Parse Claude Code `--output-format stream-json` events.

Reads JSONL events from stdin and does two things:
  1. Emits a human-readable text stream to stdout (suitable for tee'ing into
     the scoreboard's live log panel).
  2. Writes a usage summary JSON (model, tokens, cost, turns) to the path
     given as argv[1] when the stream ends.

Designed to fail open: any line that isn't valid JSON is passed through
to stdout verbatim so nothing is lost if stream-json ever gets mixed with
plain text (e.g. ruflo preamble).

Usage inside a pipeline:
    claude -p "$PROMPT" --output-format stream-json --verbose \
      | python3 stream_parse.py /path/to/solo.usage.json \
      | tee -a /path/to/solo.log
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _emit(text: str) -> None:
    if not text:
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> None:
    usage_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    summary: dict = {
        "model": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_cost_usd": 0.0,
        "num_turns": 0,
        "duration_ms": 0,
        "error": None,
    }

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            _emit(line)
            continue

        t = evt.get("type")

        if t == "system" and evt.get("subtype") == "init":
            summary["model"] = evt.get("model") or summary["model"]
            tools = evt.get("tools") or []
            _emit(f"[system] model={summary['model']} tools={len(tools)}")

        elif t == "assistant":
            msg = evt.get("message") or {}
            if not summary["model"]:
                summary["model"] = msg.get("model")
            for block in msg.get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    _emit(block.get("text", ""))
                elif btype == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input") or {}
                    hint = ""
                    if "file_path" in inp:
                        hint = f" {inp['file_path']}"
                    elif "command" in inp:
                        cmd = str(inp["command"])
                        hint = f" {cmd[:80]}"
                    elif "pattern" in inp:
                        hint = f" /{inp['pattern']}/"
                    _emit(f"[tool] {name}{hint}")
                elif btype == "thinking":
                    # Skip thinking blocks from the public log.
                    continue

        elif t == "user":
            msg = evt.get("message") or {}
            for block in msg.get("content") or []:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, str):
                        if len(content) < 240:
                            _emit(f"[tool_result] {content}")
                        else:
                            _emit(
                                f"[tool_result] <{len(content)} chars> "
                                f"{content[:160]}..."
                            )
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                txt = c.get("text", "")
                                if len(txt) < 240:
                                    _emit(f"[tool_result] {txt}")
                                else:
                                    _emit(
                                        f"[tool_result] <{len(txt)} chars> "
                                        f"{txt[:160]}..."
                                    )

        elif t == "result":
            usage = evt.get("usage") or {}
            summary["input_tokens"] = int(
                usage.get("input_tokens", summary["input_tokens"])
            )
            summary["output_tokens"] = int(
                usage.get("output_tokens", summary["output_tokens"])
            )
            summary["cache_creation_input_tokens"] = int(
                usage.get("cache_creation_input_tokens", 0)
            )
            summary["cache_read_input_tokens"] = int(
                usage.get("cache_read_input_tokens", 0)
            )
            summary["total_cost_usd"] = float(
                evt.get("total_cost_usd", summary["total_cost_usd"])
            )
            summary["num_turns"] = int(
                evt.get("num_turns", summary["num_turns"])
            )
            summary["duration_ms"] = int(
                evt.get("duration_ms", summary["duration_ms"])
            )
            if not summary["model"]:
                summary["model"] = evt.get("model")
            if evt.get("subtype") and evt.get("subtype") != "success":
                summary["error"] = str(evt.get("subtype"))
            _emit(
                f"[result] model={summary['model']} "
                f"in={summary['input_tokens']} "
                f"out={summary['output_tokens']} "
                f"cache_read={summary['cache_read_input_tokens']} "
                f"cost=${summary['total_cost_usd']:.4f} "
                f"turns={summary['num_turns']}"
            )

    if usage_path:
        try:
            usage_path.write_text(json.dumps(summary, indent=2))
        except Exception as exc:
            sys.stderr.write(f"[stream_parse] could not write usage: {exc}\n")


if __name__ == "__main__":
    main()
