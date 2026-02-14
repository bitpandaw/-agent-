from typing import Any, Dict, List, Optional
import json
from datetime import datetime
from config.config_loader import config
def init_session_state(session_id: str) -> Dict[str, Any]:
    session_state = {
        "session_id":session_id,
        "create_at": datetime.now().isoformat(),
        "turn_count":0,
        "error_count":0,
        "turn_logs":[]
    }
    return session_state


def log_turn(
    session_state: Dict[str, Any],
    turn_id: int,
    user_input: str,
    assistant_output: str,
    tool_events: List[Dict[str, Any]],
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    turn_log ={
        "session_state" : session_state,
        "turn_id" : turn_id,
        "user_input" : user_input,
        "assistant_output" : assistant_output,
        "tool_events" : tool_events,
        "error" : error
    }
    return turn_log
def flush_state(session_state: Dict[str, Any]) -> None:
    jsonw = json.dumps(session_state,ensure_ascii=False,indent=2)
    with open(config["paths"]["record_file"],"w",encoding="utf-8") as f:
        f.write(jsonw)
    pass

