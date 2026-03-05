from typing import Any, Dict, List

import chromadb
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config.config_loader import config

class RetrieveRequest(BaseModel):
    query: str

app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    filepath: str = config["paths"]["knowledge_file"]
    app.state.embedding_model = SentenceTransformer(
        config["embedding"]["model_name"],
        cache_folder=config["embedding"].get("cache_dir", ".hf_cache")
    )
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    # 简单分段：按空行分割
    chunks = [chunk.strip() for chunk in content.split('\n\n') if chunk.strip()]
    chroma_client = chromadb.Client()
    app.state.collection  = chroma_client.get_or_create_collection(
        name=config["rag"]["collection_name"],
        metadata={"hnsw:space": config["rag"].get("distance", "l2")},
    )
    for i, chunk in enumerate(chunks):
        resp = httpx.post(
            "http://embedding:8011/embed",
            json={"texts": [chunk]},
            timeout=30,
        )
        vectors = resp.json()["vectors"]
        app.state.collection.add(
            ids=[f"doc_{i}"],
            embeddings=vectors,
            documents=[chunk]
        )


@app.post("/retrieve")
def retrieve_context(req: RetrieveRequest) -> list:
    """检索时多取候选再做归一化，避免 top_k=2 时第二个结果 norm 恒为 0 被误过滤。"""
    score_threshold = config["rag"]["score_threshold"]
    query_embedding = app.state.embedding_model.encode(req.query).tolist()
    top_k = config["rag"]["top_k"]
    # 多取候选(至少 2*top_k 或 10)，在更大集合上做 min-max 归一化，避免末位恒为 0
    n_candidates = max(10, top_k * 3)
    results = app.state.collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_candidates, app.state.collection.count()),
    )
    distances = results.get("distances", [[]])[0]
    documents = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    if not distances:
        return []
    d_min = min(distances)
    d_max = max(distances)
    eps = 1e-8
    final_result = []
    for i, distance in enumerate(distances):
        norm = (d_max - distance) / (d_max - d_min + eps)
        if norm >= score_threshold:
            final_result.append({
                "doc_id": ids[i] if i < len(ids) else None,
                "text": documents[i],
                "score": norm,
            })
    final_result = sorted(final_result, reverse=True, key=lambda x: x["score"])
    return final_result[:top_k]

@app.post("/retrieve_raw")
def retrieve_context_raw(req: RetrieveRequest) -> list:
    """无归一化检索：直接按 L2 距离升序返回 top_k，不做 score_threshold 过滤。用于对比实验。"""
    query_embedding = app.state.embedding_model.encode(req.query).tolist()
    top_k = config["rag"]["top_k"]
    results = app.state.collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )
    distances = results.get("distances", [[]])[0]
    documents = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    if not distances:
        return []
    # 按 L2 距离升序（越小越相似），直接返回，不做归一化
    indexed = list(zip(ids, documents, distances))
    indexed.sort(key=lambda x: x[2])
    return [
        {"doc_id": doc_id, "text": doc, "distance": dist}
        for doc_id, doc, dist in indexed
    ]
