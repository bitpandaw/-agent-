"""RAG Pipeline 服务：纯向量检索，Reranker/KG 为独立模块。"""

import os
from typing import Any, Optional

import chromadb
import httpx
from fastapi import FastAPI
from langdetect import detect
from openai import OpenAI
from pydantic import BaseModel

from rag.produce_chunk import init_chunks
from config.config_loader import config
from knowledge_graph.kg_retrieve import retrieve_kg
from reranker import apply_reranker, get_reranker, is_loaded


class RetrieveRequest(BaseModel):
    query: str
    use_reranker: Optional[bool] = None  # None = use config, True/False = override


app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    if config.get("query_translation_model", {}).get("enabled", False):
        llm_cfg: dict[str, Any] = config["llm"]
        app.state.client = OpenAI(
            api_key=os.environ.get(llm_cfg["api_key_env"]),
            base_url=llm_cfg.get("base_url"),
        )
    else:
        app.state.client = None

    filepath: str = config["paths"]["knowledge_file"]
    app.state.embed_url = os.environ.get(
        "EMBEDDING_URL", "http://localhost:8011"
    )
    chroma_path: str = config["paths"].get("chroma_dir", "chroma_db")
    chroma_client: chromadb.PersistentClient = chromadb.PersistentClient(
        path=chroma_path
    )
    app.state.collection = chroma_client.get_or_create_collection(
        name=config["rag"]["collection_name"],
        metadata={"hnsw:space": config["rag"].get("distance", "l2")},
    )
    if app.state.collection.count() > 0:
        return  # 已有索引，跳过重建
    with open(filepath, "r", encoding="utf-8") as f:
        content: str = f.read()
    chunks: list[str] = init_chunks(content)
    embed_url: str = app.state.embed_url
    batch_size: int = 64
    for i in range(0, len(chunks), batch_size):
        batch: list[str] = chunks[i : i + batch_size]
        resp: httpx.Response = httpx.post(
            f"{embed_url.rstrip('/')}/embed",
            json={"texts": batch},
            timeout=60,
        )
        resp.raise_for_status()
        vectors_list: list[list[float]] = resp.json()["vectors"]
        for j, vec in enumerate(vectors_list):
            app.state.collection.add(
                ids=[f"doc_{i + j}"],
                embeddings=[vec],
                documents=[batch[j]],
            )


def _embed_query(query: str) -> list[float]:
    resp: httpx.Response = httpx.post(
        f"{app.state.embed_url.rstrip('/')}/embed",
        json={"texts": [query]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["vectors"][0]
@app.get("/reranker_status")
def reranker_status() -> dict[str, Any]:
    """检查 Reranker 是否已加载。"""
    return {"reranker_loaded": is_loaded()}


@app.get("/translate")
def translate_chinese(query: str) -> str:
    if not detect(query) in ("zh-cn", "zh"):
        return query 

    """将中文查询翻译为英文。"""
    response: Any = app.state.client.chat.completions.create(
        model=config["query_translation_model"]["model"],
        messages=[
            {"role": "system", "content": config["query_translation_model"]["system_prompt"]},
            {"role": "user", "content": query}
        ],
    )
    return response.choices[0].message.content



@app.post("/retrieve")
def retrieve_context(req: RetrieveRequest) -> list[dict[str, Any]]:
    """检索时按距离排序（距离越小越相似），可选 Reranker 精排。纯向量检索，不含 KG。"""
    query: str = req.query
    use_reranker: Optional[bool] = req.use_reranker
    if use_reranker is None:
        use_reranker = (config.get("reranker") or {}).get("enabled", False)

    query_en: str = translate_chinese(query)
    query_embedding: list[float] = _embed_query(query_en)
    top_k: int = config["rag"]["top_k"]
    reranker = get_reranker() if use_reranker else None
    n_candidates: int = max(20, top_k * 5) if reranker else max(10, top_k * 3)

    results: dict[str, Any] = app.state.collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_candidates, app.state.collection.count()),
    )
    distances: list[float] = results.get("distances", [[]])[0]
    documents: list[str] = results.get("documents", [[]])[0]
    ids: list[str] = results.get("ids", [[]])[0]
    if not distances:
        return []

    candidates: list[dict[str, Any]] = []
    for i, distance in enumerate(distances):
        candidates.append({
            "doc_id": ids[i] if i < len(ids) else None,
            "text": documents[i],
            "score": -distance,
        })
    candidates = sorted(candidates, reverse=True, key=lambda x: x["score"])

    if reranker:
        return apply_reranker(query_en, candidates, top_k, model=reranker)
    return candidates[:top_k]


class KgRetrieveRequest(BaseModel):
    query: str


@app.post("/retrieve_kg")
def retrieve_kg_endpoint(req: KgRetrieveRequest) -> list[dict[str, Any]]:
    """KG 检索：按实体从 Neo4j 图谱取文档，独立于向量检索。"""
    query_en: str = translate_chinese(req.query)
    kg_top_k: int = config.get("kg", {}).get("top_k") or config["rag"]["top_k"] * 2
    return retrieve_kg(query_en, top_k=kg_top_k)


@app.post("/retrieve_raw")
def retrieve_context_raw(req: RetrieveRequest) -> list[dict[str, Any]]:
    """无归一化检索：直接按 L2 距离升序返回 top_k，不做 score_threshold 过滤。用于对比实验。"""
    query_embedding: list[float] = _embed_query(req.query)
    top_k: int = config["rag"]["top_k"]
    results: dict[str, Any] = app.state.collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )
    distances: list[float] = results.get("distances", [[]])[0]
    documents: list[str] = results.get("documents", [[]])[0]
    ids: list[str] = results.get("ids", [[]])[0]
    if not distances:
        return []
    # 按 L2 距离升序（越小越相似），直接返回，不做归一化
    indexed: list[tuple[str, str, float]] = list(zip(ids, documents, distances))
    indexed.sort(key=lambda x: x[2])
    return [
        {"doc_id": doc_id, "text": doc, "distance": dist}
        for doc_id, doc, dist in indexed
    ]
