"""计算器工具。"""

import time
from typing import Any

from tools._result import make_result


def calculator(action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """计算数学表达式。"""
    start: float = time.perf_counter()
    expression: str = action["expression"]
    try:
        payload = eval(expression, {"__builtins__": {}}, {})
        return make_result(
            True, "S_ADD", "add success", payload,
            (time.perf_counter() - start) * 1000
        )
    except Exception as e:
        return make_result(
            False, "E_ADD", f"add failed: {e}", None,
            (time.perf_counter() - start) * 1000
        )
