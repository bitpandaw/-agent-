import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from config.config_loader import config


def init_session_state(session_id: str) -> Dict[str, Any]:
    session_state: Dict[str, Any] = {
        "session_id": session_id,
        "create_at": datetime.now().isoformat(),
        "turn_count": 0,
        "error_count": 0,
        "turn_logs": [],
    }
    return session_state


def log_turn(
    session_state: Dict[str, Any], turn_result: Dict[str, Any]
) -> Dict[str, Any]:
    turn_log: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "turn_id": turn_result.get("turn_id"),
        "user_input": turn_result.get("user_input", ""),
        "assistant_output": turn_result.get("assistant_output", ""),
        "tool_events": turn_result.get("tool_events", []),
        "error": turn_result.get("error"),
    }
    session_state.setdefault("turn_logs", []).append(turn_log)
    session_state["turn_count"] = session_state.get("turn_count", 0) + 1

    has_tool_error: bool = any(
        isinstance(event, dict) and (event.get("ok") is False)
        for event in turn_log["tool_events"]
    )
    if turn_log["error"] is not None or has_tool_error:
        session_state["error_count"] = session_state.get("error_count", 0) + 1
    return turn_log


def flush_state(session_state: Dict[str, Any]) -> None:
    jsonw: str = json.dumps(session_state, ensure_ascii=False, indent=2)
    record_path: Path = Path(config["paths"]["record_file"])
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with open(record_path, "w", encoding="utf-8") as f:
        f.write(jsonw)
