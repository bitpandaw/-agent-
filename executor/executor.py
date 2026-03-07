"""Executor 模块：执行 TOOL_REGISTRY 中注册的工具。"""

import time
from typing import Any


def make_result(
    tool_name: str,
    ok: bool,
    code: str,
    message: str,
    payload: Any,
    latency_ms: float,
) -> dict[str, Any]:
    """构造标准工具返回结果。"""
    return {
        "tool_name": tool_name,
        "ok": ok,
        "code": code,
        "message": message,
        "payload": payload,
        "latency_ms": round(latency_ms, 2),
    }


def execute_actions(
    plan_actions: list[dict[str, Any]],
    tool_registry: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """执行 plan_actions 中的所有工具调用。"""
    tool_events: list[dict[str, Any]] = []

    for action in plan_actions:
        start: float = time.perf_counter()
        tool_name: str | None = action.get("tool_name")
        tool_args: Any = action.get("tool_args")
        tool: Any = tool_registry.get(tool_name)
        if tool is None:
            tool_events.append(
                make_result(
                    tool_name, False, "E_TOOL_NOT_FOUND", f"Unknown tool: {tool_name}",
                    None, (time.perf_counter() - start) * 1000
                )
            )
            continue
        try:
            raw: Any = tool(tool_args, context)
            required = {"ok", "code", "message", "payload", "latency_ms"}
            if isinstance(raw, dict) and required.issubset(raw.keys()):
                raw["tool_name"] = tool_name
                tool_events.append(raw)
            else:
                tool_events.append(
                    make_result(
                    tool_name, False, "E_TOOL_CONTRACT", "工具返回非法形式",
                    raw, (time.perf_counter() - start) * 1000
                )
                )
        except TypeError as e:
            tool_events.append(
                make_result(
                    tool_name, False, "E_TOOL_ARG", f"参数返回错误: {e}",
                    None, (time.perf_counter() - start) * 1000
                )
            )
        except Exception as e:
            tool_events.append(
                make_result(
                    tool_name, False, "E_TOOL_EXEC", f"工具执行错误: {e}",
                    None, (time.perf_counter() - start) * 1000
                )
            )
    return tool_events
