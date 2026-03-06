import os
from typing import Optional

from fastapi import FastAPI
from langdetect import LangDetectException, detect
from openai import OpenAI
from pydantic import BaseModel

import chromadb
import httpx

from config.config_loader import config


class RetrieveRequest(BaseModel):
    query: str
    use_reranker: Optional[bool] = None  # None = use config, True/False = override


app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    if config.get("query_translation_model", {}).get("enabled", False):
        llm_cfg = config["llm"]
        app.state.client = OpenAI(
            api_key=os.environ.get(llm_cfg["api_key_env"]),
            base_url=llm_cfg.get("base_url"),
        )
    else:
        app.state.client = None

    reranker_cfg = config.get("reranker", {}) or {}
    if reranker_cfg.get("enabled", False) and reranker_cfg.get("model"):
        try:
            from sentence_transformers import CrossEncoder

            app.state.reranker = CrossEncoder(reranker_cfg["model"])
        except Exception as e:
            print(f"Warning: Reranker load failed: {e}, disabling.")
            app.state.reranker = None
    else:
        app.state.reranker = None

    filepath: str = config["paths"]["knowledge_file"]
    app.state.embed_url = os.environ.get(
        "EMBEDDING_URL", "http://localhost:8011"
    )
    chroma_path = config["paths"].get("chroma_dir", "chroma_db")
    chroma_client = chromadb.PersistentClient(path=chroma_path)
    app.state.collection = chroma_client.get_or_create_collection(
        name=config["rag"]["collection_name"],
        metadata={"hnsw:space": config["rag"].get("distance", "l2")},
    )
    if app.state.collection.count() > 0:
        return  # 已有索引，跳过重建
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    chunks = [chunk.strip() for chunk in content.split("\n\n") if chunk.strip()]
    embed_url = app.state.embed_url
    batch_size = 64
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        resp = httpx.post(
            f"{embed_url.rstrip('/')}/embed",
            json={"texts": batch},
            timeout=60,
        )
        resp.raise_for_status()
        vectors_list = resp.json()["vectors"]
        for j, vec in enumerate(vectors_list):
            app.state.collection.add(
                ids=[f"doc_{i + j}"],
                embeddings=[vec],
                documents=[batch[j]],
            )


def _embed_query(query: str) -> list:
    resp = httpx.post(
        f"{app.state.embed_url.rstrip('/')}/embed",
        json={"texts": [query]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["vectors"][0]

@app.get("/translate")
def translate_chinese(query:str)-> str:

    response = app.state.client.chat.completions.create(
                model=config["query_translation_model"]["model"],
                messages = [
                    {"role":"system","content":config["query_translation_model"]["system_prompt"]},
                    {"role":"user","content":query}
                ],
            )
    return response.choices[0].message.content
def is_chinese(text: str) -> bool:
    if not text or not text.strip():
        return False
    try:
        return detect(text) == "zh-cn" or detect(text) == "zh"
    except LangDetectException:
        return False
def _apply_reranker(
    query: str, candidates: list, top_k: int, reranker
) -> list:
    """对候选做 Reranker 精排，返回 top_k。"""
    if not candidates or reranker is None:
        return candidates[:top_k]
    pairs = [(query, c["text"][:512]) for c in candidates]
    scores = reranker.predict(pairs)
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    indexed = list(zip(candidates, scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    reranked = [c for c, _ in indexed[:top_k]]
    for i, r in enumerate(reranked):
        r["score"] = float(indexed[i][1]) if i < len(indexed) else 0.0
    return reranked


@app.post("/retrieve")
def retrieve_context(req: RetrieveRequest) -> list:
    """检索时多取候选再做归一化，可选 Reranker 精排。"""
    score_threshold = config["rag"]["score_threshold"]
    query: str = req.query
    use_reranker = req.use_reranker
    if use_reranker is None:
        use_reranker = (config.get("reranker") or {}).get("enabled", False)

    if config.get("query_translation_model", {}).get("enabled", False) and is_chinese(query):
        query_en = translate_chinese(query)
    else:
        query_en = query

    query_embedding = _embed_query(query_en)
    top_k = config["rag"]["top_k"]
    reranker = getattr(app.state, "reranker", None) if use_reranker else None
    n_candidates = max(20, top_k * 5) if reranker else max(10, top_k * 3)

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
    candidates = []
    for i, distance in enumerate(distances):
        norm = (d_max - distance) / (d_max - d_min + eps)
        if reranker or norm >= score_threshold:
            candidates.append({
                "doc_id": ids[i] if i < len(ids) else None,
                "text": documents[i],
                "score": norm,
            })
    candidates = sorted(candidates, reverse=True, key=lambda x: x["score"])

    if reranker:
        return _apply_reranker(query_en, candidates, top_k, reranker)
    return candidates[:top_k]

@app.post("/retrieve_raw")
def retrieve_context_raw(req: RetrieveRequest) -> list:
    """无归一化检索：直接按 L2 距离升序返回 top_k，不做 score_threshold 过滤。用于对比实验。"""
    query_embedding = _embed_query(req.query)
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
