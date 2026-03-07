"""QA 记录查询工具。"""

import sqlite3
import time
from typing import Any

from config.config_loader import config
from tools._result import make_result


def query_qa_records(action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """查询历史 QA 记录。"""
    start: float = time.perf_counter()
    db_path: str = config["paths"]["db"]
    article_title: str = action.get("article_title") or ""
    keyword: str = action.get("keyword") or ""

    sql: str = "SELECT question, answer, article_titles, created_at FROM qa_records "
    params: tuple = ()
    if article_title and keyword:
        sql += "WHERE article_titles LIKE ? AND (question LIKE ? OR answer LIKE ?)"
        params = (f"%{article_title}%", f"%{keyword}%", f"%{keyword}%")
    elif article_title:
        sql += "WHERE article_titles LIKE ?"
        params = (f"%{article_title}%",)
    elif keyword:
        sql += "WHERE question LIKE ? OR answer LIKE ?"
        params = (f"%{keyword}%", f"%{keyword}%")
    else:
        sql += "LIMIT 10"

    with sqlite3.connect(db_path) as conn:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(sql, params)
        rows: list[tuple[Any, ...]] = cursor.fetchall()
        if not rows:
            return make_result(
                False, "F_DB_QUERY", "未找到匹配数据", None,
                (time.perf_counter() - start) * 1000,
            )
        lines: list[str] = [f"找到{len(rows)}条记录："]
        for i, (q, a, titles, dt) in enumerate(rows, 1):
            q_short: str = (q[:60] + "...") if len(str(q)) > 60 else str(q)
            lines.append(f"{i}. Q: {q_short} | A: {a} | 文章: {titles} | {dt}")
        return make_result(
            True, "S_DB_QUERY", "找到匹配数据", "\n".join(lines),
            (time.perf_counter() - start) * 1000,
        )
