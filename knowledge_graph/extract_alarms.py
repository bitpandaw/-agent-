"""从 equipment_knowledge.txt 中按报警号切分出每条报警的原始文本。

支持两种格式：
  - NCK/循环/驱动/PLC 报警：以纯数字开头，如 "2000 PLC 运行信息监控"
  - V70 故障/报警：以 F 或 A + 数字开头，如 "F1000：内部软件错误"

输出：knowledge_graph/extracted_alarms.json
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^SINUMERIK 808D ADVANCED\b"),
    re.compile(r"^5\.\d\s"),
    re.compile(r"^\d+\s+诊断手册"),
    re.compile(r"^SINAMICS V70 故障与报警$"),
    re.compile(r"^7\.\d\s"),
]

NCK_ALARM_RE = re.compile(r"^(\d{4,6})\s+(.+)")
V70_ALARM_RE = re.compile(r"^([FA]\d{4})(?:：|:)\s*(.+)")

SECTION_FIELD_RE = re.compile(
    r"^(说明|参数|反应|排除方法|程序继续|现象|应答)(?:：|:)\s*(.*)"
)

CATEGORY_RANGES: list[tuple[int, int, str]] = [
    (2000, 59999, "NCK"),
    (60000, 69999, "循环"),
    (300000, 399999, "驱动"),
    (400000, 499999, "PLC"),
    (700000, 799999, "PLC用户"),
]


def classify_alarm(alarm_id: str) -> str:
    if alarm_id.startswith(("F", "A")):
        return "V70"
    try:
        num = int(alarm_id)
    except ValueError:
        return "未知"
    for low, high, cat in CATEGORY_RANGES:
        if low <= num <= high:
            return cat
    return "NCK"


def is_noise_line(line: str) -> bool:
    return any(p.search(line) for p in NOISE_PATTERNS)


def parse_alarm_block(lines: list[str], alarm_id: str, alarm_text: str) -> dict[str, Any]:
    """Parse the body lines of a single alarm entry into structured fields."""
    entry: dict[str, Any] = {
        "alarm_id": alarm_id,
        "alarm_text": alarm_text.strip(),
        "category": classify_alarm(alarm_id),
        "raw_fields": {},
        "raw_text": "",
    }

    current_field: str | None = None
    field_lines: dict[str, list[str]] = {}
    body_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or is_noise_line(stripped):
            continue

        body_lines.append(stripped)
        m = SECTION_FIELD_RE.match(stripped)
        if m:
            current_field = m.group(1)
            first_content = m.group(2).strip()
            field_lines.setdefault(current_field, [])
            if first_content:
                field_lines[current_field].append(first_content)
        elif current_field:
            field_lines.setdefault(current_field, [])
            field_lines[current_field].append(stripped)

    entry["raw_fields"] = {k: "\n".join(v) for k, v in field_lines.items()}
    entry["raw_text"] = "\n".join(body_lines)
    return entry


def extract_alarms(filepath: str) -> list[dict[str, Any]]:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: file not found: {filepath}")
        sys.exit(1)

    with path.open("r", encoding="utf-8") as f:
        all_lines = f.readlines()

    alarms: list[dict[str, Any]] = []
    current_id: str | None = None
    current_text: str = ""
    current_body: list[str] = []
    in_alarm_section = False

    for line in all_lines:
        raw = line.rstrip("\n")
        stripped = raw.strip()

        if not in_alarm_section:
            if stripped.startswith("2000 PLC"):
                in_alarm_section = True
            else:
                continue

        m_nck = NCK_ALARM_RE.match(stripped)
        m_v70 = V70_ALARM_RE.match(stripped)

        if m_nck or m_v70:
            if current_id is not None:
                alarms.append(parse_alarm_block(current_body, current_id, current_text))
            if m_nck:
                current_id = m_nck.group(1)
                current_text = m_nck.group(2)
            else:
                assert m_v70 is not None
                current_id = m_v70.group(1)
                current_text = m_v70.group(2)
            current_body = []
        else:
            if current_id is not None:
                current_body.append(raw)

    if current_id is not None:
        alarms.append(parse_alarm_block(current_body, current_id, current_text))

    return alarms


def main() -> None:
    knowledge_file = str(
        Path(__file__).resolve().parent.parent / "equipment_knowledge.txt"
    )
    alarms = extract_alarms(knowledge_file)

    output_path = Path(__file__).resolve().parent / "extracted_alarms.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(alarms, f, ensure_ascii=False, indent=2)

    categories: dict[str, int] = {}
    for a in alarms:
        cat = a["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print(f"Total alarms extracted: {len(alarms)}")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
