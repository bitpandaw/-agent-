"""Embedding 服务：提供文本向量化接口。"""

from typing import Any

from fastapi import FastAPI
from sentence_transformers import SentenceTransformer

from config.config_loader import config

app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    """启动时加载 SentenceTransformer 模型。"""
    cfg: dict[str, Any] = config["embedding"]
    cache: str = cfg.get("cache_dir", ".hf_cache")
    app.state.model = SentenceTransformer(cfg["model_name"], cache_folder=cache)


@app.get("/health")
def health_check() -> dict[str, str]:
    """健康检查接口。"""
    return {"status": "ok"}


@app.post("/embed")
def embed(request_body: dict[str, Any]) -> dict[str, list[list[float]]]:
    """将文本列表转换为向量。"""
    texts: list[str] = request_body.get("texts", [])
    vectors: list[list[float]] = app.state.model.encode(texts).tolist()
    return {"vectors": vectors}
