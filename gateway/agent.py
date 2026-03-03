"""Agent 核心逻辑：initialize_runtime、run_turn、load_knowledge_base。"""
import os
from typing import Any, Dict
from config.config_loader import config
from openai import OpenAI
from orchestrator.orchestrator import run_orchestrator
from planner.planner import build_turn_input
from rag.rag_pipeline import index_documents, load_and_chunk_document
from tools.tool_registry import TOOL_REGISTRY, get_embedding_model
import chromadb


def initialize_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """初始化共享运行时，不含 conversation。"""
    chroma_client = chromadb.Client()
    embedding_model = get_embedding_model()
    runtime = {
        "client": OpenAI(
            api_key=os.environ.get(cfg["llm"]["api_key_env"]),
            base_url=cfg["llm"]["base_url"],
        ),
        "config": cfg,
        "collection": chroma_client.get_or_create_collection(
            name=cfg["rag"]["collection_name"],
            metadata={"hnsw:space": cfg["rag"].get("distance", "l2")},
        ),
        "tool_registry": TOOL_REGISTRY,
        "embedding_model": embedding_model,
    }
    return runtime


def load_knowledge_base(cfg: Dict[str, Any], runtime: Dict[str, Any]) -> None:
    """加载知识库并建立索引。pipeline 逻辑在 rag 模块。"""
    filepath = cfg["paths"]["knowledge_file"]
    chunks = load_and_chunk_document(filepath)
    index_documents(chunks, runtime)


def run_turn(
    user_input: str,
    context: Dict[str, Any],
    session_state: Dict[str, Any],
) -> Dict[str, Any]:
    """执行单轮对话。"""
    conversation = context["conversation"]
    conversation.append({"role": "user", "content": user_input})
    turn_input = build_turn_input(
        session_state["session_id"],
        session_state["turn_count"] + 1,
        user_input,
    )
    turn_result = run_orchestrator(turn_input, context)
    return turn_result
