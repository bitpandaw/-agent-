import sys
from pathlib import Path
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
from typing import Any, Dict, List
from planner.planner import plan_actions
from executor.executor import execute_actions
def run_orchestrator(turn_input: dict[str, Any],context: dict[str, Any]) -> dict[str, Any]:
    conversation = context["conversation"]
    user_input = turn_input["user_input"]
    turn_id = turn_input["turn_id"]
    all_tool_events = []
    assistant_output = ""
    max_steps = 10
    for step in range(max_steps):
        plan_actions_results = plan_actions(turn_input,context)
        actions = plan_actions_results["actions"]
        last_msg = context["conversation"][-1]
        if  not actions:
            assistant_output = last_msg.get("content", "")
            break
        else:
            tool_events = execute_actions(actions,context["tool_registry"],context)
            all_tool_events.extend(tool_events)
            for idx,tool_event in enumerate(tool_events):
                    conversation.append({
                        "role": "tool",
                        "content":str(tool_event),
                        "name":tool_event["tool_name"],
                        "tool_call_id":actions[idx]["tool_call_id"]
                    })
    turn_result = {
        "turn_id":turn_id,
        "user_input":user_input,
        "assistant_output":assistant_output,
        "tool_events":all_tool_events,
        "error":None
    }
    return turn_result