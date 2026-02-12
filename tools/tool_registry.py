# tool_registry.py
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def calculator(expression: str):
    # Keep eval constrained to avoid arbitrary code execution.
    try:
        return eval(expression, {"__builtins__": {}}, {})
    except Exception as e:
        return f"Calculator error: {e}"

def search_knowledge(query: str, collection, top_k: int = 2) -> str:
    """Search for relevant documents."""
    query_embedding = model.encode(query).tolist()
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
    except Exception as e:
        return f"Vector DB query failed: {e}"

    documents = results.get("documents", [[]])[0]
    if not documents:
        return "No relevant documents found."
    return "Found relevant documents:\n\n" + "\n\n---\n\n".join(documents)
def query_fault_history(equipment_id=None, fault_type=None):
    """
    TODO（你来实现）
    
    提示：
    1. 连接数据库 conn = sqlite3.connect('fault_history.db')
    2. 根据参数构建SQL查询
       - 如果两个参数都没传：SELECT * FROM fault_records LIMIT 10
       - 如果只传了equipment_id：WHERE equipment_id = ?
       - 如果只传了fault_type：WHERE fault_type = ?
       - 如果都传了：WHERE equipment_id = ? AND fault_type = ?
    3. 执行查询，获取结果
    4. 格式化返回（可以返回JSON字符串或文本描述）
    
    返回格式示例：
    "找到3条记录：
    1. EQ001 - 轴承异响 - 2025-01-15 - 解决方案：更换轴承 - 停机2.5小时
    2. EQ001 - 轴承异响 - 2025-01-20 - 解决方案：加注润滑油 - 停机1.0小时
    ..."
    """
    pass
# Tool registry
tool_registry = {
    "search_knowledge": lambda query, collection, top_k=2: search_knowledge(query, collection, top_k),
    "calculator": lambda expression, collection=None: calculator(expression),
    
}

# Backward-compatible name
TOOL_REGISTRY = tool_registry
