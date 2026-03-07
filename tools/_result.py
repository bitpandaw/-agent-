"""工具返回结果构造，供各工具模块使用。"""

from typing import Any


def make_result(
    ok: bool, code: str, message: str, payload: Any, latency_ms: float
) -> dict[str, Any]:
    """构造标准工具返回结果。"""
    return {
        "ok": ok,
        "code": code,
        "message": message,
        "payload": payload,
        "latency_ms": round(latency_ms, 2),
    }
