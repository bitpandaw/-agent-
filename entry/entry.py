import sys
from pathlib import Path
from typing import Any, Dict, List
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
from config.config_loader import config
from openai import OpenAI
import state.state_logger as state_logger
import chromadb,os,uuid,time,json
from tools.tool_registry import TOOL_REGISTRY,get_embedding_model
from tools.tools_json import TOOLS_LIST
from planner.planner import build_turn_input,plan_actions
from executor.executor import execute_actions
from rag.rag_pipeline import index_documents,load_and_chunk_document
def initialize_runtime(config: Dict[str, Any]) -> Dict[str, Any]:
    chroma_client = chromadb.Client()
    embedding_model = get_embedding_model()
    context = {
        "client": OpenAI(
                api_key= os.environ.get(config["llm"]["api_key_env"]),
                base_url = config["llm"]["base_url"]
            ),
        "config":config,
        "collection":chroma_client.get_or_create_collection(name=config["rag"]["collection_name"]),
        "conversation": [
            {"role": "system", "content": "你是一个工业设备故障诊断专家。当用户提问时，使用search_knowledge工具从手册中检索相关信息，然后基于检索到的内容给出专业建议。"}
        ],
        "tool_registry":TOOL_REGISTRY,
        "embedding_model":embedding_model
    }
    return context
def run_turn(
    user_input: str,
    context: Dict[str, Any],
    session_state:Dict[str, Any]
) -> Dict[str, Any]:
    conversation = context["conversation"]
    conversation.append(
        {"role": "user", "content": user_input}
    )
    max_retries = 3
    turn_input = build_turn_input(
        session_state["session_id"],
        session_state["turn_count"] + 1,
        user_input,
        conversation
    )
    for attempt in range(max_retries):
        try:
            client = context['client']
            response = client.chat.completions.create(
                model=context["config"]["llm"]["model"],
                messages=conversation,
                tools=TOOLS_LIST
            )
            break
        except Exception as e:
            if attempt == max_retries - 1:
                raise Exception(f"与client连接失败,错误原因:{e}")
            time.sleep(10)
    ai_reply = response.choices[0].message
    if not ai_reply.tool_calls:
        conversation.append({
                "role": "assistant",
                "content": ai_reply.content,
            }
        )
        tool_events = []
    else:
        conversation.append({
            "role": "assistant",
            "content": ai_reply.content or "",
            "tool_calls":[tc.to_dict() for tc in ai_reply.tool_calls] ,
        })
        tools_schema = [{"tool_name": tc.function.name,"tool_args" : json.loads(tc.function.arguments),"tool_call_id" : tc.id }for tc in ai_reply.tool_calls]
        plan_actions_results = plan_actions(turn_input,tools_schema,client)
        tool_events = execute_actions(plan_actions_results,context["tool_registry"],context)
        for idx, tool_event in enumerate(tool_events):
            conversation.append({
                "role": "tool",
                "content":str(tool_event),
                "name":tool_event["tool_name"],
                "tool_call_id":plan_actions_results[idx]["tool_call_id"]
                }
            )
        client = context['client']
        response = client.chat.completions.create(
                model=context["config"]["llm"]["model"],
                messages=conversation,
                tools=TOOLS_LIST
        )
        ai_reply = response.choices[0].message
        conversation.append({
                "role": "assistant",
                "content": ai_reply.content,
            }
        )
    turn_result = {
        "turn_id":session_state["turn_count"] + 1,
        "user_input":user_input,
        "assistant_output":ai_reply.content,
        "tool_events":tool_events,
        "error":None
    }
    return turn_result


def main() -> None:
    context = initialize_runtime(config)
    session_id = uuid.uuid4().hex
    session_state = state_logger.init_session_state(session_id)
    print("正在加载知识库...")
    filepath = config["paths"]["knowledge_file"]
    chunks = load_and_chunk_document(filepath)
    index_documents(chunks,context)
    print("\n=== RAG驱动的设备诊断助手 ===")
    print("(输入 'quit' 退出)\n")
    while True:
        user_input = input("You:")
        if(user_input =='quit'):
            state_logger.flush_state(session_state)
            break
        turn_result = run_turn(user_input,context,session_state)
        print(turn_result["assistant_output"])
        state_logger.log_turn(session_state,turn_result)
if __name__ == "__main__":
    main()
