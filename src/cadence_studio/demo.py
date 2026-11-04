"""First-run demo batch: original synthesized audio plus clearly labelled mock annotations."""

from __future__ import annotations

import json
import shutil
from typing import Any

from .config import AUDIO_DIR
from .db import Database, new_id, utc_now
from .media import generate_demo_audio, probe_audio
from .normalizer import result_summary
from .taxonomy import get_taxonomy

DEMO_FOLDER = "demo-seed"
_DEMO_TRACKS = [
    {
        "file_name": "01_dawn-circuit.mp3",
        "caption": "一首温暖的晨光电子小品。柔和的合成器铺底从远处浮现，轻盈的电子脉冲像窗边的光斑，随后加入干净的四拍鼓点与一层空气感琶音。整体没有明显人声，情绪从安静逐渐转向明亮的期待感，适合品牌开场、晨间 Vlog 或轻科技叙事。",
        "short": "温暖晨光电子，柔和琶音与轻四拍，逐步明亮。",
        "genre": ["genre-71", "genre-48"],
        "mood": ["mood-4", "mood-8", "mood-15"],
        "bpm": 96,
        "key": "G",
        "mode": "major",
        "instruments": ["instrument-108", "instrument-106", "instrument-parent-18", "instrument-85"],
        "scene": ["scene-26", "scene-62", "scene-71"],
        "structure": [
            ("Intro", "前奏", 0, 8, 0.25),
            ("Build-up", "推进段", 8, 16, 0.54),
            ("Drop", "爆发段", 16, 24, 0.78),
            ("Outro", "尾奏", 24, 28, 0.35),
        ],
        "raw": "A warm electronic miniature at approximately 96 BPM in G major. It opens with a soft synth pad and a filtered pulse, then adds a clean four-on-the-floor kick and airy arpeggios. Instrumental. The mood moves from calm and intimate to hopeful and gently uplifting. Structure: intro 0-8s, build 8-16s, main groove 16-24s, outro 24-28s.",
    },
    {
        "file_name": "02_rain-on-tape.mp3",
        "caption": "带有磁带质感的雨夜氛围。低频略显朦胧，电钢琴和弦被刻意做旧，细碎的噪声像窗外的雨。没有鼓点冲击，只有缓慢的呼吸感与一丝怀旧。适合深夜电台、独白、记忆闪回类画面。",
        "short": "雨夜磁带氛围，朦胧电钢琴与怀旧噪声。",
        "genre": ["genre-17", "genre-167"],
        "mood": ["mood-15", "mood-19", "mood-31"],
        "bpm": 72,
        "key": "D",
        "mode": "minor",
        "instruments": ["instrument-72", "instrument-124", "instrument-108"],
        "scene": ["scene-37", "scene-28", "scene-70"],
        "structure": [
            ("Intro", "前奏", 0, 7, 0.2),
            ("Verse", "主歌", 7, 18, 0.34),
            ("Bridge", "桥段", 18, 23, 0.4),
            ("Outro", "尾奏", 23, 28, 0.22),
        ],
        "raw": "A lo-fi ambient sketch around 72 BPM in D minor. Felt piano or electric piano chords, tape hiss and soft rain-like noise. No drums, no vocals. Intimate, nostalgic and slightly melancholic, with a loose rubato feel. Sections: intro, a longer verse-like development, a short bridge, and a fading outro.",
    },
    {
        "file_name": "03_neon-run.mp3",
        "caption": "一首紧凑的霓虹电子快跑。合成器贝斯与切分鼓组提供持续推进力，明亮的和弦短促有力，像夜色中的车流。没有主唱，适合运动剪辑、科技产品节奏段落与都市夜景。",
        "short": "霓虹电子快跑，切分鼓组与明亮合成器。",
        "genre": ["genre-71", "genre-48", "genre-100"],
        "mood": ["mood-9", "mood-27", "mood-11"],
        "bpm": 124,
        "key": "A",
        "mode": "minor",
        "instruments": ["instrument-85", "instrument-parent-51", "instrument-107"],
        "scene": ["scene-88", "scene-69", "scene-71"],
        "structure": [
            ("Intro", "前奏", 0, 4, 0.3),
            ("Build-up", "推进段", 4, 10, 0.55),
            ("Drop", "爆发段", 10, 21, 0.9),
            ("Breakdown", "骤减段", 21, 24, 0.4),
            ("Drop", "爆发段", 24, 28, 0.92),
        ],
        "raw": "A driving electronic track at roughly 124 BPM in A minor. Syncopated drums, a punchy synth bass, bright stabs and a short filtered build. Instrumental. Energetic, confident and neon-lit; suitable for sports or technology edits. The arrangement has two main drops with a brief breakdown.",
    },
    {
        "file_name": "04_slow-bloom.mp3",
        "caption": "缓慢绽放的室内乐片段。钢琴以留白的方式陈述主题，弦乐在远处轻轻铺开，像一段没有说出口的告白。动态克制，情绪温暖而略带感伤，适合片尾、人物特写与品牌情绪片。",
        "short": "留白钢琴与远处弦乐，温暖克制的室内乐。",
        "genre": ["genre-273", "genre-243"],
        "mood": ["mood-18", "mood-20", "mood-16"],
        "bpm": 63,
        "key": "F",
        "mode": "major",
        "instruments": ["instrument-71", "instrument-82", "instrument-80"],
        "scene": ["scene-3", "scene-70", "scene-79"],
        "structure": [
            ("Intro", "前奏", 0, 6, 0.18),
            ("Verse", "主歌", 6, 15, 0.3),
            ("Chorus", "副歌", 15, 23, 0.52),
            ("Outro", "尾奏", 23, 28, 0.24),
        ],
        "raw": "A restrained chamber-pop miniature at about 63 BPM in F major. Solo piano states a sparse theme; strings enter quietly in the distance. Wordless, intimate and bittersweet, with a slow dynamic bloom. Structure: intro, verse-like piano statement, a fuller chorus-like swell, and a short outro.",
    },
]


def _tag(tag_id: str, source: str, confidence: float = 0.82) -> dict[str, Any] | None:
    taxonomy = get_taxonomy()
    tag = taxonomy.get(tag_id)
    if not tag:
        return None
    result = {
        "id": tag["id"],
        "name_zh": tag["zh"],
        "name_en": tag["en"],
        "confidence": confidence,
        "source_label": tag["en"] if len(source) > 60 else source,
        "mapped": False,
    }
    if tag["category"] == "Genre":
        lineage = taxonomy.hierarchy_for(tag_id)
        result.update(
            {
                "category": "Genre",
                "level": int(tag.get("genre_level", 1) or 1),
                "parent_id": tag.get("genre_parent_id", ""),
                "path": [entry.get("en", "") for entry in lineage],
                "hierarchy": [
                    {
                        "id": entry["id"],
                        "name_zh": entry["zh"],
                        "name_en": entry["en"],
                        "level": int(entry.get("genre_level", 1) or 1),
                    }
                    for entry in lineage
                ],
            }
        )
    return result


def create_demo_batch(db: Database) -> dict[str, Any]:
    existing = db.list_batches(query="演示批次", limit=1)["items"]
    for batch in existing:
        if batch.get("mode") == "demo":
            return db.get_batch(batch["id"]) or batch
    folder = AUDIO_DIR / DEMO_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    batch_id = new_id("bat")
    batch_audio_dir = folder
    spec = {
        "modules": [
            "caption",
            "genre",
            "mood",
            "bpm_key",
            "instruments",
            "structure",
            "scene",
            "vocal",
            "language",
            "production",
            "quality",
            "extra",
        ],
        "language": "zh",
        "caption_length": "medium",
        "structure_detail": "sections",
        "lyrics_timestamps": False,
        "include_confidence": True,
        "taxonomy_mode": "strict",
        "custom_instruction": "",
        "custom_fields": [],
        "audio_model_prompt": "",
        "output_language_note": "",
        "_demo": True,
    }
    batch = db.create_batch(
        "演示批次 · 四首原创氛围音乐",
        spec,
        {
            "inference_route_id": "demo",
            "inference_route": {"id": "demo", "name": "Demo Audio Model", "model": "demo-music-8b"},
            "llm_route_id": "demo",
            "llm_route": {"id": "demo", "name": "Demo Normalizer", "model": "demo-normalizer"},
            "created_at": utc_now(),
        },
        note="首启演示数据：音频为本地生成的原创合成片段，标注结果为明确标记的演示样例，不代表真实模型输出。可随时删除。",
        mode="demo",
        batch_id=batch_id,
    )
    items = []
    for index, track in enumerate(_DEMO_TRACKS, 1):
        item_id = new_id("itm")
        target = batch_audio_dir / f"{item_id}.mp3"
        if not target.exists():
            generate_demo_audio(target, variant=index - 1, seconds=28)
        probe = probe_audio(target)
        items.append(
            {
                "id": item_id,
                "position": index,
                "file_name": track["file_name"],
                "stored_path": str(target),
                "inference_path": str(target),
                "mime": "audio/mpeg",
                "size_bytes": target.stat().st_size,
                "sha256": "",
                "duration_sec": probe.get("duration_sec"),
                "sample_rate": probe.get("sample_rate"),
                "channels": probe.get("channels"),
                "bitrate": probe.get("bitrate"),
            }
        )
    db.add_items(batch_id, items)
    for item, track in zip(items, _DEMO_TRACKS, strict=False):
        tags_genre = [t for gid in track["genre"] if (t := _tag(gid, track["raw"][:80], 0.84))]
        tags_mood = [t for mid in track["mood"] if (t := _tag(mid, track["raw"][:80], 0.8))]
        tags_inst = [t for iid in track["instruments"] if (t := _tag(iid, track["raw"][:80], 0.78))]
        tags_scene = [t for sid in track["scene"] if (t := _tag(sid, track["raw"][:80], 0.75))]
        sections = [
            {
                "label": label,
                "label_zh": zh,
                "start_sec": start,
                "end_sec": end,
                "energy": energy,
                "confidence": 0.72,
                "description": "演示结构段",
            }
            for label, zh, start, end, energy in track["structure"]
        ]
        normalized = {
            "caption": {"text": track["caption"], "short": track["short"], "language": "zh"},
            "genre": {
                "items": tags_genre,
                "primary": tags_genre[0] if tags_genre else None,
                "secondary": tags_genre[1:],
                "reason": "演示样例：按音频特征手动构造，用于展示界面与导出格式。",
            },
            "mood": {
                "tags": tags_mood,
                "dominant": tags_mood[0] if tags_mood else None,
                "valence": 0.2 if "慢" in track["caption"] else 0.45,
                "energy": round(min(0.95, track["bpm"] / 140), 2),
                "reason": "演示样例，不代表真实模型判断。",
            },
            "bpm_key": {
                "bpm": track["bpm"],
                "bpm_confidence": 0.86,
                "key": track["key"],
                "mode": track["mode"],
                "time_signature": "4/4",
                "groove": "演示节奏描述",
                "notes": "演示样例",
            },
            "instruments": {
                "primary": tags_inst,
                "secondary": [],
                "notes": "演示样例：乐器标签用于展示目录映射。",
            },
            "structure": {"sections": sections, "notes": "演示结构，非真实分析结果。"},
            "scene": {"primary": tags_scene[0] if tags_scene else None, "secondary": tags_scene[1:], "reason": "演示用途建议。"},
            "vocal": {
                "present": False,
                "tags": [],
                "lead": {"gender": "unknown", "timbre": "", "delivery": ""},
                "notes": "演示音频为纯器乐。",
            },
            "language": {"primary": None, "secondary": [], "instrumental": True, "notes": "纯器乐。"},
            "production": {
                "era": "2020s",
                "production_style": "演示用合成氛围",
                "mix_character": "柔和、宽空间、低动态",
                "texture": "合成器与噪声",
                "quality_flags": [],
            },
            "quality": {"score": 82, "usable": True, "issues": [], "notes": "演示音频，非商业素材。"},
            "extra": {"tags": [], "notes": ""},
            "unmapped": [],
            "_meta": {
                "schema_version": "1.1.0",
                "taxonomy_version": get_taxonomy().version,
                "requested_modules": spec["modules"],
                "warnings": ["这是演示数据，不是音频模型的真实输出。"],
                "validated": True,
            },
        }
        summary = result_summary(normalized)
        db.update_item(
            item["id"],
            status="completed",
            stage="completed",
            progress=100,
            raw_text=track["raw"],
            llm_raw_text=json.dumps(normalized, ensure_ascii=False, indent=2),
            normalized_json=normalized,
            summary_json=summary,
            timings_json={
                "demo": True,
                "inference_ms": 0,
                "normalization_ms": 0,
                "total_ms": 0,
            },
            inference_model="Demo Audio Model · 非真实输出",
            llm_model="Demo Normalizer · 非真实输出",
            finished_at=utc_now(),
        )
    db.update_batch(batch_id, status="completed", finished_at=utc_now())
    db.add_event("demo_seeded", "演示批次已创建", batch_id=batch_id)
    return db.get_batch(batch_id) or batch


def remove_demo(db: Database, batch_id: str) -> None:
    batch = db.get_batch(batch_id)
    if not batch or batch.get("mode") != "demo":
        return
    db.delete_batch(batch_id)
    shutil.rmtree(AUDIO_DIR / DEMO_FOLDER, ignore_errors=True)
