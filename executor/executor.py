import time
from typing import Any, Dict, List


def make_result(
    tool_name: str,
    ok: bool,
    code: str,
    message: str,
    payload: Any,
    latency_ms: float,
) -> Dict[str, Any]:
    return {
        "tool_name": tool_name,
        "ok": ok,
        "code": code,
        "message": message,
        "payload": payload,
        "latency_ms": round(latency_ms, 2),
    }


def execute_actions(
    plan_actions: List[Dict[str, Any]],
    tool_registry: Dict[str, Any],
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    tool_events: List[Dict[str, Any]] = []
    
    for action in plan_actions:
        start = time.perf_counter()
        tool_name = action.get("tool_name")
        tool_args = action.get("tool_args")
        tool = tool_registry.get(tool_name)
        if tool is None:
            tool_events.append(
                make_result(
                    tool_name, False, "E_TOOL_NOT_FOUND", f"Unknown tool: {tool_name}",
                    None, (time.perf_counter() - start) * 1000
                )
            )
            continue
        try:
            raw = tool(tool_args, context)
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
