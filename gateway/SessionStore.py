import threading
from datetime import datetime
from typing import Dict, Any
class SessionStore:
    def __init__(self,system_prompt: str) -> None:
        self.system_prompt = system_prompt
        self.session_store = {}
        self.lock = threading.Lock()
    def get_or_create(self,session_id: str) -> Dict[str, Any]:
        with self.lock:
            if session_id in self.session_store:
                return self.session_store[session_id]
            else:
                session ={
                    "session_state":self.init_session_state(session_id),
                    "conversation":[{"role":"system","content":self.system_prompt}],
                    "lock": threading.Lock()
                }
                self.session_store[session_id] = session
                return session
    def init_session_state(self,session_id: str) -> Dict[str, Any]:
        return {
        "session_id": session_id,
        "create_at": datetime.now().isoformat(),
        "turn_count": 0,
        "error_count": 0,
        "turn_logs": []
    }