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
        tool_name = action.get("tool_name")
        tool_args = action.get("tool_args",{})
        tool_call_id = action.get("tool_call_id")
        if not tool_name:
            continue
        elif tool_name == "query_fault_history":
            if not tool_args["equipment_id"]:
                tool_args["equipment_id"]=None
            if not tool_args["fault_type"]:
                tool_args["fault_type"]=None
        actions.append({"tool_name":tool_name,"tool_args":tool_args,"tool_call_id":tool_call_id})
    return actions


