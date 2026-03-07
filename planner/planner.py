"""Planner 模块：调用 LLM 解析 tool_calls。"""

import json
import time
from typing import Any, Optional

from tools.tools_json import TOOLS_LIST



def plan_actions(
    turn_input: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """调用 LLM 获取 tool_calls，解析为 actions 列表。"""
    result: dict[str, Any] = {"actions": []}
    actions: list[dict[str, Any]] = []
    conversation: list[dict[str, Any]] = context["conversation"]
    max_retries: int = 3

    for attempt in range(max_retries):
        try:
            client: Any = context["client"]
            response: Any = client.chat.completions.create(
                model=context["config"]["llm"]["model"],
                messages=conversation,
                tools=TOOLS_LIST
            )
            break
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"LLM request failed after {max_retries} retries: {e}"
                ) from e
            time.sleep(10)

    ai_reply = response.choices[0].message
    if not ai_reply.tool_calls:
        conversation.append({
            "role": "assistant",
            "content": ai_reply.content,
        })
        return result

    conversation.append({
        "role": "assistant",
        "content": ai_reply.content or "",
        "tool_calls": [tc.to_dict() for tc in ai_reply.tool_calls],
    })

    tools_schema: list[dict[str, Any]] = [
        {
            "tool_name": tc.function.name,
            "tool_args": json.loads(tc.function.arguments),
            "tool_call_id": tc.id,
        }
        for tc in ai_reply.tool_calls
    ]

    for action in tools_schema:
        if not isinstance(action, dict):
            continue
        tool_name: Optional[str] = action.get("tool_name")
        tool_args: dict[str, Any] = action.get("tool_args", {}) or {}
        tool_call_id: Optional[str] = action.get("tool_call_id")
        if not isinstance(tool_args, dict):
            tool_args = {}
        if tool_name == "query_qa_records":
            tool_args.setdefault("article_title", None)
            tool_args.setdefault("keyword", None)
        if not tool_name:
            continue
        actions.append({
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_call_id": tool_call_id,
        })

    result["actions"] = actions
    return result
