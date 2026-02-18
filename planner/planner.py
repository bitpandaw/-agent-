from typing import Any, Dict, List
def build_turn_input(
    session_id: str,
    turn_id: int,
    user_input: str,
    conversation: List[Dict[str, Any]],
) -> Dict[str, Any]:
    Result = {"session_id":session_id,
              "turn_id":turn_id,
              "user_input":user_input,
              "conversation":conversation
              }
    return Result

def plan_actions(
    turn_input: Dict[str, Any],
    tools_schema: List[Dict[str, Any]],
    llm_client: Any,
) -> List[Dict[str, Any]]:
    actions=[]
    for action in tools_schema:
        if not isinstance(action,dict):
            continue
        tool_name = action.get("tool_name")
        tool_args = action.get("tool_args",{})
        tool_call_id = action.get("tool_call_id")
        if not isinstance(tool_args,dict):
            tool_args = {}
        if tool_name == "query_fault_history":
            tool_args.setdefault("equipment_id", None)
            tool_args.setdefault("fault_type", None)
        if not tool_name: 
            continue
        actions.append({"tool_name":tool_name,"tool_args":tool_args,"tool_call_id":tool_call_id})
    return actions


