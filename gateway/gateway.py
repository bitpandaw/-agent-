import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from config.config_loader import config
from orchestrator.orchestrator import initialize_runtime, run_turn
from gateway.SessionStore import SessionStore
import state.state_logger as state_logger


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    turn_id: int


app = FastAPI()


@app.on_event("startup")
def startup_event() -> None:
    """初始化 runtime 和 session_store。"""
    print("正在努力启动中......")
    global session_store
    app.state.runtime = initialize_runtime(config)
    session_store = SessionStore(config["llm"]["system_prompt"])


@app.get("/health")
def health_check() -> dict:
    """健康检查接口。"""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id: str = request.session_id or str(uuid.uuid4())
    runtime: Any = app.state.runtime
    session: dict[str, Any] = session_store.get_or_create(session_id)
    turn_context: dict[str, Any] = {
        **runtime,
        "conversation": session["conversation"],
    }
    with session["lock"]:
        turn_result: dict[str, Any] = run_turn(
            request.message, turn_context, session["session_state"]
        )
        state_logger.log_turn(session["session_state"], turn_result)
    return ChatResponse(
        reply=turn_result["assistant_output"],
        session_id=session_id,
        turn_id=turn_result["turn_id"],
    )
