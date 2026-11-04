"""Add a 1-based human sequence column to the vendored reference document.

The source snapshot uses IDs such as ``scene-2`` because its first row is the
table header. Machines keep those stable IDs; humans get a 1-based sequence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "src" / "cadence_studio" / "resources" / "taxonomy.json"
DOC = ROOT / "docs" / "product" / "taxonomy-reference.md"
NOTE = "> **序号说明**：下表“序号”从 1 开始，每个大类独立编号。`标签 ID` 是稳定的机器标识，保留来源快照的原始编号（因此可能从 2 开始）；API、导出和映射只使用标签 ID，展示序号不参与任何数据关联。\n"


def main() -> None:
    data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    seq = {tag["id"]: tag["seq"] for tag in data["tags"]}
    original = DOC.read_text(encoding="utf-8")
    if "| 序号 | 标签 ID（稳定） |" in original:
        print(f"{DOC} already has a 1-based sequence column")
        return
    lines = original.splitlines()
    out: list[str] = []
    inserted_note = False
    header_done = False
    need_separator = False
    row_re = re.compile(r"^\| `([^`]+)` \|")
    for line in lines:
        if not inserted_note and line.startswith("## 一、"):
            out.extend([NOTE, ""])
            inserted_note = True
        if line.startswith("| 标签 ID |"):
            line = line.replace("| 标签 ID |", "| 序号 | 标签 ID（稳定） |", 1)
            header_done = True
            need_separator = True
        elif need_separator and line.startswith("| ---"):
            cells = line.strip().strip("|").split("|")
            line = "| " + " | ".join(["---"] * (len(cells) + 1)) + " |"
            need_separator = False
        else:
            match = row_re.match(line)
            if match and match.group(1) in seq:
                line = line.replace(f"| `{match.group(1)}` |", f"| {seq[match.group(1)]} | `{match.group(1)}` |", 1)
        out.append(line)
    if not inserted_note:
        out.insert(5, NOTE)
    if not header_done:
        raise SystemExit("No tag table header found")
    DOC.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Updated {DOC} with {len(seq)} sequence numbers")


if __name__ == "__main__":
    main()
