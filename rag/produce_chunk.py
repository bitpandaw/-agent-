"""HotpotQA 段落级分块：每个 chunk = Title + 段落。"""


def init_chunks(content: str) -> list[str]:
    """按 Title 边界分块，每块为一个完整段落（Title + 内容）。

    HotpotQA 知识文件格式：Title: XXX 后跟双换行和段落，段落间以 "Title: " 分隔。
    """
    if not content or not content.strip():
        return []
    parts: list[str] = content.split("\n\nTitle: ")
    chunks: list[str] = []
    for i, block in enumerate(parts):
        block = block.strip()
        if not block:
            continue
        if i == 0:
            chunk = block
        else:
            chunk = "Title: " + block
        chunks.append(chunk)
    return chunks