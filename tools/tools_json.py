# tools_json.py
TOOLS_LIST = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a math expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expression to evaluate, e.g. '25*4'."
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the equipment knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
    "type": "function",
    "function": {
        "name": "query_fault_history",
        "description": "查询设备的历史故障记录",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "设备编号，如EQ001（可选）"
                },
                "fault_type": {
                    "type": "string", 
                    "description": "故障类型，如'轴承异响'（可选）"
                }
            }
            # 注意：这两个参数都是可选的，不要写required
        }
    }
}
]
