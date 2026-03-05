import threading
from datetime import datetime
from typing import Any, Dict

class SessionStore:
    """线程安全的会话存储，管理 conversation 与 session_state。"""

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt
        self.session_store: Dict[str, Any] = {}
        self.lock = threading.Lock()

    def get_or_create(self, session_id: str) -> Dict[str, Any]:
        with self.lock:
            if session_id in self.session_store:
                return self.session_store[session_id]
            else:
                session = {
                    "session_state": self.init_session_state(session_id),
                    "conversation": [{"role": "system", "content": self.system_prompt}],
                    "lock": threading.Lock(),
                }
                self.session_store[session_id] = session
                return session

    def init_session_state(self, session_id: str) -> Dict[str, Any]:
        """初始化单会话的 session_state。"""
        return {
            "session_id": session_id,
            "create_at": datetime.now().isoformat(),
            "turn_count": 0,
            "error_count": 0,
            "turn_logs": [],
        }