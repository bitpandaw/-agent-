from typing import Any, Dict, List
import inspect

def call_tool(
    tool_func: Any,
    tool_args: Dict[str, Any],
    runtime: Dict[str, Any],
) -> Any:
    kwargs = dict(tool_args or {})
    sig = inspect.signature(tool_func)
    params = sig.parameters
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if "collection" in params or has_var_kw:
        kwargs.setdefault("collection",collection)
    try:
        return tool_func(**kwargs)
    except TypeError as e:
        return f"tool call argument error:{e}"
def execute_actions(
    plan_actions: List[Dict[str, Any]],
    tool_registry: Dict[str, Any],
    runtime: Dict[str, Any],
) -> List[Dict[str, Any]]:
    pass

