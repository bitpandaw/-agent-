"""将 structured_alarms.json 导入 Neo4j，构建故障诊断知识图谱。

节点类型：Alarm, Component, MachineData, Solution, AlarmCategory, FaultType, Equipment
关系类型：HAS_SOLUTION, AFFECTS_COMPONENT, INVOLVES_PARAM, REFERENCES,
          BELONGS_TO, MAPS_TO, HAS_FAULT_RECORD

用法：
  1. 确保 Neo4j 已通过 docker compose 启动
  2. python knowledge_graph/build_graph.py
  3. 打开 http://localhost:7474 查看图谱
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j_808d")


def clear_graph(tx: Any) -> None:
    tx.run("MATCH (n) DETACH DELETE n")


def create_constraints(tx: Any) -> None:
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Alarm) REQUIRE a.alarm_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Component) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:MachineData) REQUIRE m.md_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cat:AlarmCategory) REQUIRE cat.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (ft:FaultType) REQUIRE ft.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (eq:Equipment) REQUIRE eq.equipment_id IS UNIQUE",
    ]
    for c in constraints:
        tx.run(c)


def create_alarm_categories(tx: Any) -> None:
    categories = ["NCK", "循环", "驱动", "PLC", "PLC用户", "V70"]
    for cat in categories:
        tx.run("MERGE (c:AlarmCategory {name: $name})", name=cat)


def import_alarm(tx: Any, alarm: Dict[str, Any]) -> None:
    tx.run(
        """
        MERGE (a:Alarm {alarm_id: $alarm_id})
        SET a.alarm_text = $alarm_text,
            a.category = $category,
            a.description = $description,
            a.reaction = $reaction,
            a.continue_method = $continue_method
        """,
        alarm_id=alarm.get("alarm_id", ""),
        alarm_text=alarm.get("alarm_text", ""),
        category=alarm.get("category", ""),
        description=alarm.get("description", ""),
        reaction=alarm.get("reaction", []),
        continue_method=alarm.get("continue_method", ""),
    )

    cat = alarm.get("category", "")
    if cat:
        tx.run(
            """
            MATCH (a:Alarm {alarm_id: $alarm_id})
            MERGE (c:AlarmCategory {name: $cat})
            MERGE (a)-[:BELONGS_TO]->(c)
            """,
            alarm_id=alarm["alarm_id"],
            cat=cat,
        )

    for sol_text in alarm.get("solution", []):
        if not sol_text.strip():
            continue
        tx.run(
            """
            MATCH (a:Alarm {alarm_id: $alarm_id})
            MERGE (s:Solution {text: $sol_text})
            MERGE (a)-[:HAS_SOLUTION]->(s)
            """,
            alarm_id=alarm["alarm_id"],
            sol_text=sol_text.strip(),
        )

    for comp in alarm.get("components", []):
        if not comp.strip():
            continue
        tx.run(
            """
            MATCH (a:Alarm {alarm_id: $alarm_id})
            MERGE (c:Component {name: $comp})
            MERGE (a)-[:AFFECTS_COMPONENT]->(c)
            """,
            alarm_id=alarm["alarm_id"],
            comp=comp.strip(),
        )

    for md_id in alarm.get("machine_data_ids", []):
        if not md_id.strip():
            continue
        tx.run(
            """
            MATCH (a:Alarm {alarm_id: $alarm_id})
            MERGE (m:MachineData {md_id: $md_id})
            MERGE (a)-[:INVOLVES_PARAM]->(m)
            """,
            alarm_id=alarm["alarm_id"],
            md_id=md_id.strip(),
        )

    for ref_id in alarm.get("referenced_alarms", []):
        ref_str = str(ref_id).strip()
        if not ref_str:
            continue
        tx.run(
            """
            MATCH (a:Alarm {alarm_id: $alarm_id})
            MERGE (ref:Alarm {alarm_id: $ref_id})
            MERGE (a)-[:REFERENCES]->(ref)
            """,
            alarm_id=alarm["alarm_id"],
            ref_id=ref_str,
        )


def import_fault_history(tx: Any, db_path: str) -> None:
    """从 fault_history.db 导入设备和故障类型节点。"""
    if not Path(db_path).exists():
        print(f"  Warning: {db_path} not found, skipping fault history import.")
        return

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT equipment_id FROM fault_records")
        for (eq_id,) in cursor.fetchall():
            tx.run(
                "MERGE (e:Equipment {equipment_id: $eq_id})",
                eq_id=eq_id,
            )

        cursor.execute("SELECT DISTINCT fault_type FROM fault_records")
        for (ft,) in cursor.fetchall():
            tx.run(
                "MERGE (f:FaultType {name: $ft})",
                ft=ft,
            )

        cursor.execute(
            "SELECT DISTINCT equipment_id, fault_type FROM fault_records"
        )
        for eq_id, ft in cursor.fetchall():
            tx.run(
                """
                MATCH (e:Equipment {equipment_id: $eq_id})
                MATCH (f:FaultType {name: $ft})
                MERGE (e)-[:HAS_FAULT_RECORD]->(f)
                """,
                eq_id=eq_id,
                ft=ft,
            )


def create_fault_type_mappings(tx: Any) -> None:
    """建立故障类型到报警的初始映射（基于关键词匹配）。

    LLM 抽取后可以在 structured_alarms.json 里补充更精确的映射，
    这里先做一个基于关键词的粗粒度映射作为 fallback。
    """
    mappings: Dict[str, List[str]] = {
        "轴承异响": ["振动", "异响", "轴承", "噪声", "噪音"],
        "温度异常": ["温度", "过热", "散热", "冷却"],
        "振动异常": ["振动", "振荡", "共振", "不平衡"],
        "液压系统故障": ["液压", "压力", "油泵", "密封"],
    }
    for fault_type, keywords in mappings.items():
        for kw in keywords:
            tx.run(
                """
                MATCH (f:FaultType {name: $ft})
                MATCH (a:Alarm)
                WHERE a.description CONTAINS $kw
                   OR a.alarm_text CONTAINS $kw
                MERGE (f)-[:MAPS_TO]->(a)
                """,
                ft=fault_type,
                kw=kw,
            )


def print_stats(session: Any) -> None:
    result = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC")
    print("\n--- Graph Statistics ---")
    for record in result:
        print(f"  {record['label']}: {record['cnt']}")

    result = session.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC")
    print("  ---")
    for record in result:
        print(f"  {record['rel']}: {record['cnt']}")


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    input_path = base_dir / "structured_alarms.json"
    db_path = str(base_dir.parent / "fault_history.db")

    if not input_path.exists():
        print("Error: structured_alarms.json not found. Run llm_extract.py first.")
        return

    with input_path.open("r", encoding="utf-8") as f:
        alarms: List[Dict[str, Any]] = json.load(f)

    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
        print("Connected.")
    except Exception as e:
        print(f"Error: Cannot connect to Neo4j: {e}")
        print("Make sure Neo4j is running (docker compose up -d neo4j)")
        return

    with driver.session() as session:
        print("Clearing existing graph...")
        session.execute_write(clear_graph)

        print("Creating constraints...")
        session.execute_write(create_constraints)

        print("Creating alarm categories...")
        session.execute_write(create_alarm_categories)

        print(f"Importing {len(alarms)} alarms...")
        for i, alarm in enumerate(alarms):
            session.execute_write(import_alarm, alarm)
            if (i + 1) % 100 == 0:
                print(f"  [{i + 1}/{len(alarms)}]")

        print("Importing fault history...")
        session.execute_write(import_fault_history, db_path)

        print("Creating fault type → alarm mappings...")
        session.execute_write(create_fault_type_mappings)

        print_stats(session)

    driver.close()
    print("\nDone. Open http://localhost:7474 to explore the graph.")


if __name__ == "__main__":
    main()
