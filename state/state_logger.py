from typing import Any, Dict, List, Optional


def init_session_state(session_id: str) -> Dict[str, Any]:
    pass


def log_turn(
    session_state: Dict[str, Any],
    turn_id: int,
    user_input: str,
    assistant_output: str,
    tool_events: List[Dict[str, Any]],
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pass


def flush_state(session_state: Dict[str, Any]) -> None:
    pass

