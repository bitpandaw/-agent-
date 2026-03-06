from fastapi import FastAPI
from sentence_transformers import SentenceTransformer

from config.config_loader import config

app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    cfg: dict = config["embedding"]
    cache: str = cfg.get("cache_dir", ".hf_cache")
    app.state.model = SentenceTransformer(cfg["model_name"], cache_folder=cache)

@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.post("/embed")
def embed(request_body: dict) -> dict:
    texts: list[str] = request_body.get("texts", [])
    vectors: list[list[float]] = app.state.model.encode(texts).tolist()
    return {"vectors": vectors}
