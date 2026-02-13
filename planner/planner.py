from typing import Any, Dict, List


def build_turn_input(
    session_id: str,
    turn_id: int,
    user_input: str,
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pass


def plan_actions(
    turn_input: Dict[str, Any],
    tools_schema: List[Dict[str, Any]],
    llm_client: Any,
) -> Dict[str, Any]:
    pass

