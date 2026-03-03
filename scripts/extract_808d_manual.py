#!/usr/bin/env python3
"""
从 SINUMERIK 808D ADVANCED 诊断手册 PDF 提取文本，生成 equipment_knowledge.txt 格式。
用法: python scripts/extract_808d_manual.py <pdf_path> [--output equipment_knowledge.txt]
"""
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    print("请安装 pypdf: pip install pypdf")
    sys.exit(1)


def extract_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def clean_text(text: str) -> str:
    # 移除页码标记 "-- 57 of 548 --"
    text = re.sub(r"--\s*\d+\s+of\s+\d+\s*--", "\n", text)
    # 移除重复的 "诊断手册" 页眉行（单独成行的）
    text = re.sub(r"^诊断手册\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^诊断手册, 07/2018, 6FC5398-6DP10-0RA6\s*\d*\s*\n", "", text, flags=re.MULTILINE)
    # 合并多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(text: str, min_chars: int = 60, max_chars: int = 1200) -> list[str]:
    """按报警块或双换行分割。报警格式：数字(4-6位) 空格 文本，如 2000 PLC 运行信息监控"""
    # 先按报警号分块：匹配行首 4-6 位数字+空格
    alarm_pattern = re.compile(r"(?=^\d{4,6}\s+\S)", re.MULTILINE)
    parts = alarm_pattern.split(text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p or len(p) < min_chars:
            continue
        # 若块过长，再按双换行细分
        if len(p) > max_chars:
            sub = [s.strip() for s in p.split("\n\n") if len(s.strip()) >= min_chars]
            chunks.extend(sub)
        else:
            # 过滤无效块
            if re.match(r"^[\d\s\-\.]+$", p):
                continue
            if p in ("诊断手册", "SINUMERIK", "SINUMERIK 808D ADVANCED"):
                continue
            chunks.append(p)
    return chunks


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_808d_manual.py <pdf_path> [--output output.txt]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    output_path = "equipment_knowledge.txt"
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
    project_root = Path(__file__).resolve().parent.parent
    out_file = project_root / output_path if not Path(output_path).is_absolute() else Path(output_path)
    pdf = Path(pdf_path)
    if not pdf.exists():
        print(f"错误: 文件不存在 {pdf_path}")
        sys.exit(1)
    print(f"正在提取: {pdf}")
    raw = extract_text(str(pdf))
    print(f"  原始文本约 {len(raw)} 字符")
    cleaned = clean_text(raw)
    chunks = split_into_chunks(cleaned)
    print(f"  得到 {len(chunks)} 个有效块")
    content = "\n\n".join(chunks)
    out_file.write_text(content, encoding="utf-8")
    print(f"已写入: {out_file}")


if __name__ == "__main__":
    main()
