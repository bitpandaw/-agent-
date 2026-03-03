# -*- coding: utf-8 -*-
"""Find correct doc_ids for fuzzy_5, boundary_3, boundary_5 by searching chunks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag.rag_pipeline import load_and_chunk_document

chunks = load_and_chunk_document(str(Path(__file__).resolve().parents[1] / "equipment_knowledge.txt"))

def find_doc(keyword, desc):
    for i, c in enumerate(chunks):
        if keyword in c:
            return i
    return -1

# boundary_3: 808D数据备份 - 8.1 内部数据备份章节
bidx3 = find_doc("对于有限缓存的存储器数据，可将数据备份在数控系统的永久存储器中", "data backup")
print("boundary_3 (data backup):", f"doc_{bidx3}" if bidx3 >= 0 else "NOT FOUND")

# boundary_5: SINAMICS V70故障 - 7.1/7.2 章节
bidx5 = find_doc("SINAMICS V70 上可能出现的常见故障和报警", "SINAMICS V70")
print("boundary_5 (SINAMICS V70):", f"doc_{bidx5}" if bidx5 >= 0 else "NOT FOUND")

# fuzzy_5: 15120 动力故障（电源/掉电相关，最接近电池电量不足）
bidx_f5 = find_doc("15120 如果当前动力故障", "power failure 15120")
print("fuzzy_5 (15120 power):", f"doc_{bidx_f5}" if bidx_f5 >= 0 else "NOT FOUND")
if bidx_f5 < 0:
    bidx_f5 = find_doc("15122 电源故障后上电", "power failure 15122")
    print("fuzzy_5 (15122 power):", f"doc_{bidx_f5}" if bidx_f5 >= 0 else "NOT FOUND")
