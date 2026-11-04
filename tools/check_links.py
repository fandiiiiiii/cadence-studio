"""Check local Markdown links and images (ignore HTTP and anchors)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def check(path: Path) -> list[str]:
    problems = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for target in LINK.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "tel:")):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            problems.append(f"{path.relative_to(ROOT)} -> {target}")
    return problems


def main() -> int:
    problems = []
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in {".venv", "node_modules", "build", "dist", "data", "runtime"} for part in path.parts):
            continue
        problems.extend(check(path))
    for problem in problems:
        print(problem)
    print(f"{len(problems)} broken local links")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
