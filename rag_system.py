from openai import OpenAI
import chromadb,os,json,inspect
from tools.tool_registry import TOOL_REGISTRY, get_embedding_model
import tools.tools_json as tools
from config.config_loader import config
import time
# 初始化客户端
llm_cfg = config["llm"]
client = OpenAI(
    api_key= os.environ.get(llm_cfg["api_key_env"]),
    base_url = llm_cfg["base_url"]
)
def call_tool(tool_func,tool_args,collection):
    action = dict(tool_args or {})
    context = {"collection":collection} 
    sig = inspect.signature(tool_func)
    params = sig.parameters
    tool_name = tool_func.__name__
    if tool_name == "search_knowledge":
        context["model"] = get_embedding_model()
    elif tool_name == "query_fault_history":
        action.setdefault("equipment_id", None)
        action.setdefault("fault_type", None)
    return tool_func(action, context)
# 初始化ChromaDB
chroma_client = chromadb.Client()
collection = chroma_client.get_or_create_collection(name="equipment_knowledge")
# Step 1: 读取文档并分段
def load_and_chunk_document(filepath):
    """读取文档并按段落分割"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 简单分段：按空行分割
    chunks = [chunk.strip() for chunk in content.split('\n\n') if chunk.strip()]
    return chunks
# Step 2: 把文档块存入ChromaDB
def index_documents(chunks):
    """为文档块生成embedding并存入向量数据库"""
    model = get_embedding_model()
    for i, chunk in enumerate(chunks):
        embedding = model.encode(chunk).tolist()
        collection.add(
            ids=[f"doc_{i}"],
            embeddings=[embedding],
            documents=[chunk]
        )
    print(f"✅ 已索引 {len(chunks)} 个文档块")
# Step 4: 主Agent循环
def main():
    # 初始化：加载文档
    print("正在加载知识库...")
    chunks = load_and_chunk_document("equipment_knowledge.txt")
    index_documents(chunks)
    conversation = [
        {"role": "system", "content": "你是一个工业设备故障诊断专家。当用户提问时，使用search_knowledge工具从手册中检索相关信息，然后基于检索到的内容给出专业建议。"}
    ]

    print("\n=== RAG驱动的设备诊断助手 ===")
    print("(输入 'quit' 退出)\n")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'quit':
            break
        
        conversation.append({"role": "user", "content": user_input})
        while True:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model=llm_cfg["model"],
                        messages=conversation,
                        tools=tools.TOOLS_LIST
                    )
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise Exception(f"与client连接失败,错误原因:{e}")
                    time.sleep(10)
            ai_reply = response.choices[0].message
            if not ai_reply.tool_calls:
                conversation.append({"role": "assistant", "content": ai_reply.content})
                break
            conversation.append({
                "role": "assistant",
                "content": ai_reply.content or "",
                "tool_calls": [tc.to_dict() for tc in ai_reply.tool_calls],
            })
            for tool_call in ai_reply.tool_calls:
                tool_name = tool_call.function.name
                tool_func = TOOL_REGISTRY.get(tool_name)
                tool_args = json.loads(tool_call.function.arguments)
                if tool_func is None:
                    result = f"Unknown tool: {tool_name}"
                else:
                    result = call_tool(tool_func,tool_args,collection)
                conversation.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tool_call.id,
                    "name": tool_name
                })
        print(f"\nAI: {ai_reply.content}\n")
if __name__ == "__main__":
    main()
