"""用 DeepSeek LLM 从切分好的报警条目中批量抽取结构化三元组。

输入：knowledge_graph/extracted_alarms.json
输出：knowledge_graph/structured_alarms.json

用法：
  python knowledge_graph/llm_extract.py               # 全量处理
  python knowledge_graph/llm_extract.py --limit 10     # 只处理前 10 条（调试用）
  python knowledge_graph/llm_extract.py --resume       # 断点续跑
"""

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

EXTRACT_PROMPT = """\
你是 SINUMERIK 808D 数控系统故障诊断专家。
请从以下报警条目中提取结构化信息，严格按 JSON 格式返回，不要输出其他内容。

要求提取的字段：
- alarm_id: 报警编号（字符串）
- alarm_text: 报警标题文本
- category: 报警类别（NCK/循环/驱动/PLC/V70）
- description: 说明内容（简要概括，不超过200字）
- reaction: 系统反应（列表形式）
- solution: 排除方法（列表形式，每个步骤一条）
- continue_method: 程序继续方式
- referenced_alarms: 文中提到的其他报警编号（数组，仅编号）
- machine_data_ids: 涉及的机床数据编号（数组，如 ["MD10100", "MD11411"]）
- components: 涉及的设备部件/子系统（数组，如 ["PLC", "NCK", "主轴", "驱动"]）

返回格式示例：
{{
  "alarm_id": "2000",
  "alarm_text": "PLC 运行信息监控",
  "category": "NCK",
  "description": "PLC必须在规定时间内发出使用期限信号，否则触发报警",
  "reaction": ["NC没有准备就绪", "报警显示", "报警时NC停止"],
  "solution": ["检查机床数据MD10100中的监控时间", "确定PLC中的故障原因并清除"],
  "continue_method": "关闭/打开系统",
  "referenced_alarms": [],
  "machine_data_ids": ["MD10100"],
  "components": ["PLC", "NCK"]
}}

报警原文：
---
报警编号: {alarm_id}
报警文本: {alarm_text}
类别: {category}
{raw_text}
---
"""


def build_prompt(alarm: dict[str, Any]) -> str:
    return EXTRACT_PROMPT.format(
        alarm_id=alarm["alarm_id"],
        alarm_text=alarm["alarm_text"],
        category=alarm["category"],
        raw_text=alarm["raw_text"],
    )


def call_llm(client: OpenAI, prompt: str, model: str, max_retries: int = 3) -> dict[str, Any] | None:
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content:
                return json.loads(content)
            return None
        except json.JSONDecodeError:
            if content:
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                try:
                    return json.loads(cleaned.strip())
                except json.JSONDecodeError:
                    pass
            print(f"  JSON parse error on attempt {attempt + 1}, retrying...")
        except Exception as e:
            wait = 2 ** attempt * 5
            print(f"  API error on attempt {attempt + 1}: {e}, waiting {wait}s...")
            time.sleep(wait)
    return None


def load_progress(output_path: Path) -> dict[str, dict[str, Any]]:
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["alarm_id"]: item for item in data}
    return {}


def save_progress(results: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM batch extraction for alarm entries")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N alarms (0=all)")
    parser.add_argument("--resume", action="store_true", help="Skip already processed alarms")
    parser.add_argument("--batch-size", type=int, default=20, help="Save progress every N alarms")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    input_path = base_dir / "extracted_alarms.json"
    output_path = base_dir / "structured_alarms.json"

    if not input_path.exists():
        print("Error: extracted_alarms.json not found. Run extract_alarms.py first.")
        return

    with input_path.open("r", encoding="utf-8") as f:
        alarms: list[dict[str, Any]] = json.load(f)

    if args.limit > 0:
        alarms = alarms[: args.limit]

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY environment variable not set.")
        return

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    model = "deepseek-chat"

    done: dict[str, dict[str, Any]] = {}
    if args.resume:
        done = load_progress(output_path)
        print(f"Resuming: {len(done)} alarms already processed.")

    results: list[dict[str, Any]] = list(done.values())
    success = 0
    fail = 0
    total = len(alarms)

    print(f"Processing {total} alarms...")
    for i, alarm in enumerate(alarms):
        aid = alarm["alarm_id"]
        if aid in done:
            continue

        prompt = build_prompt(alarm)
        extracted = call_llm(client, prompt, model)

        if extracted:
            extracted["alarm_id"] = aid
            extracted["category"] = alarm["category"]
            results.append(extracted)
            done[aid] = extracted
            success += 1
        else:
            fail += 1
            print(f"  FAIL: alarm {aid}")

        progress = len(done)
        if progress % args.batch_size == 0:
            save_progress(results, output_path)

        if (i + 1) % 10 == 0 or i == total - 1:
            print(f"  [{progress}/{total}] success={success} fail={fail}")

        time.sleep(0.5)

    save_progress(results, output_path)
    print(f"\nDone. Total={len(results)} success={success} fail={fail}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
