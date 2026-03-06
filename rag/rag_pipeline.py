import os
from typing import TYPE_CHECKING, Any, Optional

from fastapi import FastAPI
from langdetect import LangDetectException, detect
from openai import OpenAI
from pydantic import BaseModel

import chromadb
import httpx

from config.config_loader import config

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


class RetrieveRequest(BaseModel):
    query: str
    use_reranker: Optional[bool] = None  # None = use config, True/False = override
    use_kg: Optional[bool] = None  # None = use config, True/False = override


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

    reranker_cfg: dict[str, Any] = config.get("reranker", {}) or {}
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
    chunks: list[str] = [
        chunk.strip() for chunk in content.split("\n\n") if chunk.strip()
    ]
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
    loaded = getattr(app.state, "reranker", None) is not None
    return {"reranker_loaded": loaded}


@app.get("/translate")
def translate_chinese(query: str) -> str:
    response: Any = app.state.client.chat.completions.create(
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
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    reranker: Optional["CrossEncoder"],
) -> list[dict[str, Any]]:
    """对候选做 Reranker 精排，返回 top_k。"""
    if not candidates or reranker is None:
        return candidates[:top_k]
    pairs: list[tuple[str, str]] = [
        (query, c["text"][:512]) for c in candidates
    ]
    scores: Any = reranker.predict(pairs)
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    indexed: list[tuple[dict[str, Any], Any]] = list(
        zip(candidates, scores)
    )
    indexed.sort(key=lambda x: x[1], reverse=True)
    reranked: list[dict[str, Any]] = [c for c, _ in indexed[:top_k]]
    for i, r in enumerate(reranked):
        r["score"] = float(indexed[i][1]) if i < len(indexed) else 0.0
    return reranked


def _fetch_kg(query: str) -> list[dict[str, Any]]:
    """从 Neo4j KG 按 query 检索，返回 [{text, doc_id}, ...]。"""
    try:
        from neo4j import GraphDatabase

        cfg = config["neo4j"]
        driver = GraphDatabase.driver(
            cfg["uri"], auth=(cfg["user"], cfg["password"])
        )
        cypher = (
            "MATCH (a:Article)-[:CONTAINS]->(s:Sentence) "
            "WHERE s.text CONTAINS $query OR a.title CONTAINS $query "
            "RETURN a.title AS article, s.text AS sentence LIMIT 15"
        )
        with driver.session() as session:
            recs = session.run(cypher, query=query).data()
        driver.close()
        return [
            {"text": r["sentence"], "doc_id": f"kg_{r['article']}", "score": 0.0}
            for r in recs
        ]
    except Exception:
        return []


def _merge_unique(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按文本前缀去重合并。"""
    seen = {d.get("text", "")[:100] for d in base}
    merged = list(base)
    for d in extra:
        key = d.get("text", "")[:100]
        if key not in seen:
            merged.append(d)
            seen.add(key)
    return merged


@app.post("/retrieve")
def retrieve_context(req: RetrieveRequest) -> list[dict[str, Any]]:
    """检索时多取候选再做归一化，可选 Reranker 精排。"""
    score_threshold: float = config["rag"]["score_threshold"]
    query: str = req.query
    use_reranker: Optional[bool] = req.use_reranker
    if use_reranker is None:
        use_reranker = (config.get("reranker") or {}).get("enabled", False)
    use_kg: Optional[bool] = req.use_kg
    if use_kg is None:
        use_kg = (config.get("rag") or {}).get("use_kg", False)

    query_en: str
    if config.get("query_translation_model", {}).get("enabled", False) and is_chinese(query):
        query_en = translate_chinese(query)
    else:
        query_en = query

    query_embedding: list[float] = _embed_query(query_en)
    top_k: int = config["rag"]["top_k"]
    reranker: Optional["CrossEncoder"] = (
        getattr(app.state, "reranker", None) if use_reranker else None
    )
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

    d_min: float = min(distances)
    d_max: float = max(distances)
    eps: float = 1e-8
    candidates: list[dict[str, Any]] = []
    for i, distance in enumerate(distances):
        norm: float = (d_max - distance) / (d_max - d_min + eps)
        if reranker or norm >= score_threshold:
            candidates.append({
                "doc_id": ids[i] if i < len(ids) else None,
                "text": documents[i],
                "score": norm,
            })
    candidates = sorted(candidates, reverse=True, key=lambda x: x["score"])

    if use_kg:
        kg_docs = _fetch_kg(query_en)
        candidates = _merge_unique(candidates, kg_docs)

    if reranker:
        return _apply_reranker(query_en, candidates, top_k, reranker)
    return candidates[:top_k]

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
