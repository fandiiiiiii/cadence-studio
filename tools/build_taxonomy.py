"""Build the normalized Cadence taxonomy from the vendored workbench snapshot.

Run from the repository root:
    python tools/build_taxonomy.py
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "cadence_studio" / "resources" / "taxonomy.source.json"
TARGET = ROOT / "src" / "cadence_studio" / "resources" / "taxonomy.json"

CATEGORY_META = OrderedDict(
    [
        (
            "Genre",
            {
                "label_zh": "曲风",
                "label_en": "Genre",
                "description": "主曲风、子曲风与融合风格；按标签 ID 作为唯一规范值。",
                "color": "violet",
            },
        ),
        (
            "Mood",
            {
                "label_zh": "情绪",
                "label_en": "Mood",
                "description": "听感情绪与能量倾向；互斥规则见 mood_rule。",
                "color": "amber",
            },
        ),
        (
            "Scene",
            {
                "label_zh": "场景",
                "label_en": "Scene",
                "description": "内容主题、使用场景、场合、季节、地点与视频用途。",
                "color": "cyan",
            },
        ),
        (
            "Instrument",
            {
                "label_zh": "乐器",
                "label_en": "Instrument",
                "description": "主奏与伴奏乐器、音色、人声织体及声音效果。",
                "color": "lime",
            },
        ),
        (
            "Vocal",
            {
                "label_zh": "人声",
                "label_en": "Vocal",
                "description": "人声有无、性别、音色、唱法与演唱形态。",
                "color": "rose",
            },
        ),
        (
            "Language",
            {
                "label_zh": "语言",
                "label_en": "Language",
                "description": "歌词或对白的主要语言、方言及多语种情况。",
                "color": "blue",
            },
        ),
        (
            "Extra",
            {
                "label_zh": "补充标签",
                "label_en": "Extra",
                "description": "土味、现场、ACG、体裁等补充语义。",
                "color": "slate",
            },
        ),
    ]
)

STRUCTURE_LABELS = [
    ("intro", "Intro", "前奏", "歌曲或音乐正式开始前建立氛围的段落。"),
    ("verse", "Verse", "主歌", "叙述性段落，旋律动机通常重复，歌词推进内容。"),
    ("pre-chorus", "Pre-Chorus", "导歌", "主歌与副歌之间的抬升段落，常制造期待。"),
    ("chorus", "Chorus", "副歌", "作品的核心记忆段落，重复度与能量通常最高。"),
    ("post-chorus", "Post-Chorus", "后副歌", "副歌之后延续 hook 或律动的短段落。"),
    ("interlude", "Interlude", "间奏", "段落之间的器乐或氛围过渡。"),
    ("bridge", "Bridge", "桥段", "提供对比、转折或新和声色彩的段落。"),
    ("instrumental", "Instrumental", "器乐段", "无人声主导的完整器乐段落。"),
    ("breakdown", "Breakdown", "骤减段", "能量与配器明显抽离，为后续回归蓄力。"),
    ("build-up", "Build-up", "推进段", "鼓点、音效或张力逐步累积，导向 drop 或副歌。"),
    ("drop", "Drop", "爆发段", "电子音乐中能量集中释放的核心段落。"),
    ("outro", "Outro", "尾奏", "作品收束、淡出或重复终止动机的段落。"),
    ("silence", "Silence", "静音", "数字静音或近似无声区间。"),
    ("spoken", "Spoken", "口语", "说话、念白或非歌唱人声。"),
    ("applause", "Applause", "掌声", "观众掌声、欢呼等现场反应。"),
    ("noise", "Noise", "噪声", "非音乐性噪声、底噪或损坏片段。"),
    ("fill", "Fill", "填充", "乐器加花或过渡，用于连接段落。"),
    ("break", "Break", "切口", "整体能量短暂停顿或抽离。"),
    ("hold", "Hold", "延长", "和弦、旋律或终止被刻意延长。"),
    ("end", "End", "结束", "音频文件结束标记。"),
]


def clean(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def aliases_for(record: dict) -> list[str]:
    values = {
        record.get("zh", ""),
        record.get("en", ""),
        record.get("path", "").split("/")[-1].strip(),
    }
    en = record.get("en", "")
    values.add(en.replace("_", " "))
    values.add(en.replace("_", "-"))
    for part in re.split(r"\s*/\s*", en):
        if part:
            values.add(part)
    for part in re.split(r"\s*/\s*", record.get("zh", "")):
        if part:
            values.add(part)
    cleaned = []
    for value in values:
        value = clean(value)
        if value and value not in {"/", "—", "-"} and value.lower() not in {x.lower() for x in cleaned}:
            cleaned.append(value)
    return sorted(cleaned)


def _norm(value: str) -> str:
    return re.sub(r"[\s\-_/·•,，.。:：;；'\"“”‘’()（）\[\]【】›]+", "", (value or "").lower())


def attach_genre_hierarchy(tags: list[dict]) -> None:
    """Add deterministic level-1/2/3 lineage to every Genre tag.

    The source table stores a path like ``Pop`` or ``Electronic › House``.
    A path equal to the tag's own name is a top-level genre; a child such as
    K-Pop (path ``Pop``) gets Pop as its parent. The normalizer never invents
    a parent: it copies these IDs from the taxonomy.
    """
    genres = [tag for tag in tags if tag["category"] == "Genre"]
    by_path: dict[str, list[dict]] = {}
    by_name: dict[str, dict] = {}
    for tag in genres:
        by_path.setdefault(_norm(tag.get("path", "")), []).append(tag)
        for value in (tag["en"], tag["zh"]):
            by_name.setdefault(_norm(value), tag)

    def lineage_for(tag: dict) -> list[str]:
        parent_id = tag.get("genre_parent_id")
        if not parent_id:
            return [tag["id"]]
        parent = next((item for item in genres if item["id"] == parent_id), None)
        return (lineage_for(parent) if parent else []) + [tag["id"]]

    for tag in genres:
        path = (tag.get("path") or "").strip()
        segments = [part.strip() for part in re.split(r"›", path) if part.strip()]
        names = {_norm(tag["en"]), _norm(tag["zh"])}
        if not segments or _norm(path) in names or (len(segments) == 1 and _norm(segments[0]) in names):
            tag["genre_level"] = 1
            tag["genre_parent_id"] = ""
            continue
        parent_path = "›".join(segments[:-1]) if len(segments) > 1 else segments[0]
        parent = None
        candidates = by_path.get(_norm(parent_path), [])
        for candidate in candidates:
            if candidate is tag:
                continue
            if _norm(candidate["en"]) == _norm(segments[-1]) or _norm(candidate["zh"]) == _norm(segments[-1]):
                parent = candidate
                break
        if parent is None:
            parent = next((candidate for candidate in candidates if candidate is not tag), None)
        if parent is None:
            parent = by_name.get(_norm(segments[-1]))
        if parent is None or parent is tag:
            tag["genre_level"] = 1
            tag["genre_parent_id"] = ""
        else:
            tag["genre_parent_id"] = parent["id"]
            tag["genre_level"] = int(parent.get("genre_level", 1)) + 1
    for tag in genres:
        tag["genre_lineage"] = lineage_for(tag)


def main() -> None:
    raw = SOURCE.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    records = data["records"]
    tags: list[dict] = []
    for record in records:
        category = record["cat"]
        tags.append(
            {
                "id": record["id"],
                "category": category,
                "row": int(record.get("row") or 0),
                "group": clean(record.get("group")),
                "path": clean(record.get("path")),
                "zh": clean(record.get("zh")),
                "en": clean(record.get("en")),
                "definition": clean(record.get("def")),
                "features": clean(record.get("features")),
                "sentiment": clean(record.get("sentiment")),
                "aliases": aliases_for(record),
            }
        )
    tags.sort(key=lambda tag: (list(CATEGORY_META).index(tag["category"]), tag["row"], tag["id"]))
    attach_genre_hierarchy(tags)
    # Human-facing numbering starts at 1 in every category. The canonical
    # source IDs (e.g. genre-2) remain stable for machines and old exports.
    sequence: Counter[str] = Counter()
    for tag in tags:
        sequence[tag["category"]] += 1
        tag["seq"] = sequence[tag["category"]]
    counts = Counter(tag["category"] for tag in tags)
    groups = OrderedDict()
    for category in CATEGORY_META:
        seen: list[str] = []
        for tag in tags:
            if tag["category"] == category and tag["group"] and tag["group"] not in seen:
                seen.append(tag["group"])
        groups[category] = seen

    structure = {
        "version": "structure-2026-11-03",
        "labels": [
            {
                "id": slug,
                "en": en,
                "zh": zh,
                "definition": definition,
            }
            for slug, en, zh, definition in STRUCTURE_LABELS
        ],
    }

    payload = {
        "schema_version": "1.0.0",
        "version": "workbench-2026-11-03",
        # Fixed for reproducible CI diffs; update deliberately with a new snapshot.
        "generated_at": "2026-11-05T00:00:00+00:00",
        "source": {
            "filename": "workbench-2026-11-03.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "declared_sha256": "7d5c041eae9078e8d03c14497dcc82479972816c26fa10869a598c345f9d3035",
            "label_count": len(tags),
            "category_counts": dict(counts),
            "note": "标签定义来自用户提供的音乐标签工作台快照；系统只做结构化转换，不改写定义。",
        },
        "categories": {
            category: {
                "key": category,
                **meta,
                "count": counts[category],
                "groups": groups[category],
            }
            for category, meta in CATEGORY_META.items()
        },
        "tags": tags,
        "rules": data.get("rules", []),
        "formulas": data.get("formulas", []),
        "mood_rule": data.get("mood_rule", ""),
        "structure": structure,
        "field_registry": {
            "bpm": {"label_zh": "速度", "unit": "BPM", "type": "number", "range": [20, 300]},
            "key": {"label_zh": "调性", "type": "string", "example": "C#"},
            "mode": {"label_zh": "调式", "type": "enum", "values": ["major", "minor", "modal", "unknown"]},
            "time_signature": {"label_zh": "拍号", "type": "string", "example": "4/4"},
            "energy": {"label_zh": "能量", "type": "number", "range": [0, 1]},
            "valence": {"label_zh": "情绪效价", "type": "number", "range": [-1, 1]},
            "danceability": {"label_zh": "舞曲性", "type": "number", "range": [0, 1]},
            "acousticness": {"label_zh": "原声感", "type": "number", "range": [0, 1]},
            "instrumentalness": {"label_zh": "器乐倾向", "type": "number", "range": [0, 1]},
            "explicit": {"label_zh": "显式内容", "type": "boolean"},
            "quality_score": {"label_zh": "音频质量", "type": "number", "range": [0, 100]},
            "confidence": {"label_zh": "置信度", "type": "number", "range": [0, 1]},
        },
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET} with {len(tags)} tags")
    print("Category counts:", dict(counts))
    print("Source sha256:", payload["source"]["sha256"])


if __name__ == "__main__":
    main()
