"""
signalweaver_mcp/server.py

MCP server that wraps any tool call through SignalWeaver's gate before execution.

Flow:
    LLM decides to call a tool
        → MCP routes to SignalWeaver /gate/evaluate
        → proceed:  tool executes normally, result returned
        → gate:     tool blocked, explanation + suggestion returned to LLM
        → refuse:   hard block, logged, LLM told to stop

Usage:
    python server.py

Requires:
    pip install mcp httpx

Environment:
    SW_BASE_URL      SignalWeaver backend URL (default: http://localhost:8000)
    SW_API_KEY       API key for SignalWeaver (if auth enabled)
    SW_PROFILE       Policy profile name to use (optional)
"""

import asyncio
import httpx
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Config ────────────────────────────────────────────────────────────────────

SW_BASE_URL = os.getenv("SW_BASE_URL", "http://localhost:8000")
SW_API_KEY  = os.getenv("SW_API_KEY", "")
SW_PROFILE  = os.getenv("SW_PROFILE", "")

# ── Server ────────────────────────────────────────────────────────────────────

app = Server("signalweaver-gate")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if SW_API_KEY:
        h["X-API-Key"] = SW_API_KEY
    return h


async def _gate_evaluate(request_summary: str, arousal: str = "unknown", dominance: str = "unknown") -> dict:
    """
    Call SignalWeaver /gate/evaluate.
    Returns the full response dict.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{SW_BASE_URL}/gate/evaluate",
            headers=_headers(),
            json={
                "request_summary": request_summary,
                "arousal": arousal,
                "dominance": dominance,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _summarise_call(tool_name: str, arguments: dict) -> str:
    """
    Build a human-readable summary of a tool call for the gate to evaluate.
    Keeps it short and meaningful — the gate does keyword/embedding matching,
    so surface-level intent matters.
    """
    # Flatten args into a short phrase
    arg_parts = []
    for k, v in arguments.items():
        if isinstance(v, str) and len(v) < 80:
            arg_parts.append(f"{k}={v!r}")
        elif isinstance(v, (int, float, bool)):
            arg_parts.append(f"{k}={v}")
        else:
            arg_parts.append(f"{k}=[{type(v).__name__}]")

    args_str = ", ".join(arg_parts) if arg_parts else "no args"
    return f"tool call: {tool_name}({args_str})"


def _format_gate_block(gate_result: dict, tool_name: str) -> str:
    """
    Format a gate/refuse decision into a clear LLM-facing message.
    """
    decision     = gate_result.get("decision", "gate")
    interpretation = gate_result.get("interpretation", "")
    suggestion   = gate_result.get("suggestion", "")
    explanations = gate_result.get("explanations") or []
    next_actions = gate_result.get("next_actions") or []
    ethos_refs   = gate_result.get("ethos_refs") or []
    log_id       = gate_result.get("log_id", "?")
    trace_id     = gate_result.get("trace_id", "?")

    lines = [
        f"⛔ SignalWeaver [{decision.upper()}] — tool `{tool_name}` was not executed.",
        "",
        f"Reason: {interpretation}" if interpretation else "",
        f"Suggestion: {suggestion}" if suggestion else "",
    ]

    if explanations:
        lines += ["", "Conflicts detected:"]
        for exp in explanations:
            lines.append(f"  • {exp}")

    if next_actions:
        lines += ["", f"Next actions available: {', '.join(next_actions)}"]

    if ethos_refs:
        lines += ["", f"Ethos references: {', '.join(ethos_refs)}"]

    lines += [
        "",
        f"Audit: log_id={log_id}, trace_id={trace_id}",
        f"Replay: GET {SW_BASE_URL}/gate/replay/{trace_id}",
    ]

    return "\n".join(l for l in lines if l is not None)


# ── Tool definitions ──────────────────────────────────────────────────────────
#
# These are the REAL tools the LLM can request.
# Every call passes through the gate before execution.
#
# In production you'd register your own tools here.
# The gate logic is tool-agnostic — it evaluates the intent summary.

DEMO_TOOLS = [
    types.Tool(
        name="send_email",
        description="Send an email to a recipient.",
        inputSchema={
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body":    {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        },
    ),
    types.Tool(
        name="delete_file",
        description="Permanently delete a file from the filesystem.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="process_payment",
        description="Process a payment transaction.",
        inputSchema={
            "type": "object",
            "properties": {
                "amount":   {"type": "number",  "description": "Amount in GBP"},
                "to":       {"type": "string",  "description": "Recipient account"},
                "memo":     {"type": "string",  "description": "Payment description"},
            },
            "required": ["amount", "to"],
        },
    ),
    types.Tool(
        name="read_file",
        description="Read the contents of a file.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="run_shell_command",
        description="Execute a shell command.",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    ),
    types.Tool(
        name="sw_check_health",
        description="Check SignalWeaver backend health and current policy status.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="sw_list_anchors",
        description="List active SignalWeaver truth anchors (policy rules).",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="sw_get_logs",
        description="Retrieve recent SignalWeaver gate decision logs.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max logs to return (default 10)"},
            },
        },
    ),
]


# ── Tool registry ─────────────────────────────────────────────────────────────
#
# Map tool name → actual execution function.
# These are the real side-effect functions — they only run if the gate says proceed.

async def _exec_send_email(args: dict) -> str:
    # DEMO: simulate email send
    return f"[DEMO] Email sent to {args['to']} — subject: {args['subject']!r}"


async def _exec_delete_file(args: dict) -> str:
    # DEMO: simulate file deletion
    return f"[DEMO] File deleted: {args['path']}"


async def _exec_process_payment(args: dict) -> str:
    # DEMO: simulate payment
    return f"[DEMO] Payment of £{args['amount']} sent to {args['to']}"


async def _exec_read_file(args: dict) -> str:
    try:
        with open(args["path"], "r") as f:
            return f.read()[:2000]  # cap at 2k chars
    except Exception as e:
        return f"Error reading file: {e}"


async def _exec_run_shell_command(args: dict) -> str:
    # DEMO: real execution gated behind SignalWeaver
    try:
        result = subprocess.run(
            args["command"], shell=True, capture_output=True, text=True, timeout=10
        )
        return result.stdout or result.stderr or "(no output)"
    except Exception as e:
        return f"Error: {e}"


async def _exec_sw_check_health(_args: dict) -> str:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{SW_BASE_URL}/health", headers=_headers())
        data = resp.json()
    return json.dumps({"signalweaver": data, "profile": SW_PROFILE or "default", "base_url": SW_BASE_URL}, indent=2)


async def _exec_sw_list_anchors(_args: dict) -> str:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{SW_BASE_URL}/anchors/", headers=_headers())
        data = resp.json()
    return json.dumps(data, indent=2)


async def _exec_sw_get_logs(args: dict) -> str:
    limit = args.get("limit", 10)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            f"{SW_BASE_URL}/gate/logs",
            headers=_headers(),
            params={"limit": limit},
        )
        data = resp.json()
    return json.dumps(data, indent=2)


# Internal tools that bypass the gate (they're inspecting SignalWeaver itself)
BYPASS_GATE = {"sw_check_health", "sw_list_anchors", "sw_get_logs"}

TOOL_EXECUTORS = {
    "send_email":        _exec_send_email,
    "delete_file":       _exec_delete_file,
    "process_payment":   _exec_process_payment,
    "read_file":         _exec_read_file,
    "run_shell_command": _exec_run_shell_command,
    "sw_check_health":   _exec_sw_check_health,
    "sw_list_anchors":   _exec_sw_list_anchors,
    "sw_get_logs":       _exec_sw_get_logs,
}


# ── MCP handlers ──────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return DEMO_TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    Every tool call comes through here.
    Gate check happens BEFORE execution for all non-SW tools.
    """

    # ── SignalWeaver introspection tools bypass the gate ──────────────────────
    if name in BYPASS_GATE:
        executor = TOOL_EXECUTORS.get(name)
        if executor:
            result = await executor(arguments)
            return [types.TextContent(type="text", text=result)]
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    # ── Build intent summary for gate evaluation ──────────────────────────────
    request_summary = _summarise_call(name, arguments)

    # ── Gate evaluation ───────────────────────────────────────────────────────
    try:
        gate_result = await _gate_evaluate(request_summary)
    except httpx.ConnectError:
        # SignalWeaver is down — fail open with warning, or fail closed
        # Current behaviour: FAIL CLOSED (safe default)
        return [types.TextContent(
            type="text",
            text=(
                f"⚠️  SignalWeaver is unreachable at {SW_BASE_URL}.\n"
                f"Tool `{name}` was NOT executed (fail-closed policy).\n"
                f"Start SignalWeaver and retry."
            ),
        )]
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"⚠️  Gate evaluation error: {e}\nTool `{name}` was NOT executed.",
        )]

    decision = gate_result.get("decision", "gate")

    # ── Proceed: execute the tool ─────────────────────────────────────────────
    if decision == "proceed":
        executor = TOOL_EXECUTORS.get(name)
        if not executor:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

        # Prepend a brief audit note so the LLM knows the gate ran
        trace_id = gate_result.get("trace_id", "?")
        log_id   = gate_result.get("log_id", "?")

        try:
            result = await executor(arguments)
        except Exception as e:
            result = f"Tool execution error: {e}"

        audit_note = f"✅ SignalWeaver [PROCEED] — trace_id={trace_id}, log_id={log_id}\n\n"
        return [types.TextContent(type="text", text=audit_note + result)]

    # ── Gate / Refuse: block execution ────────────────────────────────────────
    blocked_msg = _format_gate_block(gate_result, name)
    return [types.TextContent(type="text", text=blocked_msg)]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    print(f"[SignalWeaver MCP] Starting — connected to {SW_BASE_URL}", file=sys.stderr)
    if SW_PROFILE:
        print(f"[SignalWeaver MCP] Policy profile: {SW_PROFILE}", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
