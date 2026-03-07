"""Orchestrator 模块：基于 Function Calling 的多步工具调用循环。"""

import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from executor.executor import execute_actions
from planner.planner import plan_actions
from tools.tool_registry import TOOL_REGISTRY


def build_turn_input(
    session_id: str,
    turn_id: int,
    user_input: str,
) -> dict[str, Any]:
    """构建单轮输入上下文。"""
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "user_input": user_input,
    }

def run_turn(
    user_input: str,
    context: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    """执行单轮对话。"""
    conversation: list[dict[str, Any]] = context["conversation"]
    conversation.append({"role": "user", "content": user_input})
    turn_input: dict[str, Any] = build_turn_input(
        session_state["session_id"],
        session_state["turn_count"] + 1,
        user_input,
    )
    turn_result: dict[str, Any] = run_orchestrator(turn_input, context)
    return turn_result


def initialize_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    """初始化运行时环境。"""
    runtime: dict[str, Any] = {
        "client": OpenAI(
            api_key=os.environ.get(cfg["llm"]["api_key_env"]),
            base_url=cfg["llm"]["base_url"],
        ),
        "config": cfg,
        "tool_registry": TOOL_REGISTRY,
    }
    return runtime


def run_orchestrator(
    turn_input: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """执行多步工具调用循环。"""
    conversation: list[dict[str, Any]] = context["conversation"]
    user_input: str = turn_input["user_input"]
    turn_id: int = turn_input["turn_id"]
    all_tool_events: list[dict[str, Any]] = []
    assistant_output: str = ""
    max_steps: int = 3

    for _ in range(max_steps):
        plan_actions_results: dict[str, Any] = plan_actions(turn_input, context)
        actions: list[dict[str, Any]] = plan_actions_results["actions"]
        last_msg: dict[str, Any] = context["conversation"][-1]
        if not actions:
            assistant_output = last_msg.get("content", "")
            break
        tool_events: list[dict[str, Any]] = execute_actions(
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

    turn_result: dict[str, Any] = {
        "turn_id": turn_id,
        "user_input": user_input,
        "assistant_output": assistant_output,
        "tool_events": all_tool_events,
        "error": None,
    }
    return turn_result