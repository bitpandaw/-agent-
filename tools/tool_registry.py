# tool_registry.py
from sentence_transformers import SentenceTransformer
import sqlite3,time
from config.config_loader import config
from pathlib import Path
from typing import Any, Dict, Callable
from rag.rag_pipeline import retrieve_context
_embedding_model = None
def make_result(ok: bool, code: str, message: str, payload: Any, latency_ms: float) -> Dict[str, Any]:
    return {
        "ok": ok,
        "code": code,
        "message": message,
        "payload": payload,
        "latency_ms": round(latency_ms, 2)
    }

ToolFunc = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
def get_embedding_model():
    global _embedding_model 
    if _embedding_model is not None:
        return _embedding_model
    else:
        embedding_model = config["embedding"]
        cache_dir_cfg = embedding_model.get("cache_dir", ".hf_cache")
        cache_dir = Path(cache_dir_cfg)
        if not cache_dir.is_absolute():
            cache_dir = (Path(__file__).resolve().parent.parent / cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        _embedding_model = SentenceTransformer(
            embedding_model["model_name"], 
            cache_folder=cache_dir
        )
        return _embedding_model
def calculator(action: Dict[str, Any], context: Dict[str, Any])->Dict[str,Any]:
    start = time.perf_counter()
    expression = action["expression"]
    try:
        payload = eval(expression, {"__builtins__": {}}, {})
        return make_result(True, "S_ADD", "add success", payload, (time.perf_counter() - start) * 1000)
    except Exception as e:
        return make_result(False, "E_ADD", f"add failed: {e}", None, (time.perf_counter() - start) * 1000)
def search_knowledge(action: Dict[str, Any], context: Dict[str, Any])->Dict[str,Any]:
    start = time.perf_counter()
    query = action["query"]
    max_retries = 3
    rag = config["rag"]
    for attempt in range(max_retries):
        try:
            results = retrieve_context(query,context,rag["top_k"],rag["score_threshold"])
            break
        except Exception as e:
            if attempt == max_retries - 1:
                return make_result(False, "E_RAG_QUERY", "查询超时ChromaDB", None, (time.perf_counter() - start) * 1000)
            time.sleep(10)
    if not results:
        return make_result(False, "E_RAG_DOC", "没有找到文件", None, (time.perf_counter() - start) * 1000)
    result = "Found relevant documents:\n\n" + "\n\n---\n\n"
    for index, item in enumerate(results, start=1):
        result += f"rank: {index} score: {item['score']} text: {item['text']}\n"
    return make_result(True, "S_RAG_QUERY", "查询到ChromaDB", result, (time.perf_counter() - start) * 1000)
def query_fault_history(action: Dict[str, Any], context: Dict[str, Any])->Dict[str,Any]:
    start = time.perf_counter()
    conn = sqlite3.connect('fault_history.db')
    cursor = conn.cursor()
    params = ()
    equipment_id = action["equipment_id"]
    fault_type = action["fault_type"]
    sql = "SELECT * FROM fault_records "
    if equipment_id and fault_type:
        sql+="WHERE equipment_id = ? AND fault_type = ?"
        params = (equipment_id, fault_type)
    elif equipment_id and not fault_type:
        sql+="WHERE equipment_id = ?"
        params = (equipment_id,)
    elif not equipment_id and fault_type:
        sql+="WHERE fault_type = ?"
        params = (fault_type,)
    else :
       sql+="LIMIT 10"
    cursor.execute(sql,params)
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return make_result(False, "F_DB_QUERY", "未找到匹配数据", None, (time.perf_counter() - start) * 1000)
    lines = [f"找到{len(rows)}条记录："]
    for i,row in enumerate(rows, 1):
        _,ft,date,sol,hours,eq =row
        lines.append(f"{i}. {eq} - {ft} - {date} - 解决方案：{sol} - 停机{hours}小时")
    conn.close()
    return make_result(True, "S_DB_QUERY", "找到匹配数据", "\n".join(lines), (time.perf_counter() - start) * 1000)

# Tool registry
TOOL_REGISTRY: Dict[str, ToolFunc] = {
    "search_knowledge": search_knowledge,
    "calculator": calculator,
    "query_fault_history":query_fault_history
}
