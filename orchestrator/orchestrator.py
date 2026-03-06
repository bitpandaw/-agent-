import os
import sys
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from executor.executor import execute_actions
from planner.planner import build_turn_input, plan_actions
from tools.tool_registry import TOOL_REGISTRY


def run_turn(
    user_input: str,
    context: Dict[str, Any],
    session_state: Dict[str, Any],
) -> Dict[str, Any]:
    """执行单轮对话。"""
    conversation: list[Dict[str, Any]] = context["conversation"]
    conversation.append({"role": "user", "content": user_input})
    turn_input: Dict[str, Any] = build_turn_input(
        session_state["session_id"],
        session_state["turn_count"] + 1,
        user_input,
    )
    turn_result: Dict[str, Any] = run_orchestrator(turn_input, context)
    return turn_result


def initialize_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    runtime: Dict[str, Any] = {
        "client": OpenAI(
            api_key=os.environ.get(cfg["llm"]["api_key_env"]),
            base_url=cfg["llm"]["base_url"],
        ),
        "config": cfg,
        "tool_registry": TOOL_REGISTRY,
    }
    return runtime

def run_orchestrator(
    turn_input: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    conversation: list[Dict[str, Any]] = context["conversation"]
    user_input: str = turn_input["user_input"]
    turn_id: int = turn_input["turn_id"]
    all_tool_events: list[Dict[str, Any]] = []
    assistant_output: str = ""
    max_steps: int = 10
    for step in range(max_steps):
        plan_actions_results: Dict[str, Any] = plan_actions(turn_input, context)
        actions: list[Dict[str, Any]] = plan_actions_results["actions"]
        last_msg: Dict[str, Any] = context["conversation"][-1]
        if not actions:
            assistant_output = last_msg.get("content", "")
            break
        else:
            tool_events: list[Dict[str, Any]] = execute_actions(
                actions, context["tool_registry"], context
            )
            all_tool_events.extend(tool_events)
            for idx, tool_event in enumerate(tool_events):
                conversation.append({
                    "role": "tool",
                    "content": str(tool_event),
                    "name": tool_event["tool_name"],
                    "tool_call_id": actions[idx]["tool_call_id"],
                })
    turn_result: Dict[str, Any] = {
        "turn_id": turn_id,
        "user_input": user_input,
        "assistant_output": assistant_output,
        "tool_events": all_tool_events,
        "error": None,
    }
    return turn_result