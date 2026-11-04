"""Tiny OpenAI-compatible mock used only for local end-to-end tests."""

import json
from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    requested = []
    for message in body.get("messages", []):
        if message.get("role") == "user":
            try:
                payload = json.loads(message.get("content") or "{}")
                requested = payload.get("requested_modules") or []
            except json.JSONDecodeError:
                pass
    tag_genre = {
        "id": "genre-146",
        "name_zh": "冷爵士",
        "name_en": "Cool Jazz",
        "confidence": 0.86,
        "source_label": "Modal Jazz",
        "mapped": True,
    }
    tag_mood = {
        "id": "mood-15",
        "name_zh": "轻松/放松",
        "name_en": "Chill",
        "confidence": 0.9,
        "source_label": "chill",
        "mapped": False,
    }
    result = {
        "caption": {
            "text": "一段温暖、克制的电子氛围，合成器铺底与轻柔脉冲逐渐展开，像清晨窗边的光。整体无人声，情绪从安静走向明亮。",
            "short": "温暖电子氛围，安静渐亮。",
            "language": "zh",
        },
        "genre": {
            "primary": tag_genre,
            "secondary": [
                {
                    "id": "genre-77",
                    "name_zh": "氛围电子",
                    "name_en": "Ambient",
                    "confidence": 0.81,
                    "source_label": "ambient",
                    "mapped": False,
                }
            ],
            "fusion": ["ambient electronic"],
            "reason": "以合成器铺底和缓慢展开为主，接近 cool jazz 的克制感与氛围电子的结构。",
        },
        "mood": {
            "tags": [
                tag_mood,
                {
                    "id": "mood-4",
                    "name_zh": "温暖/友好的",
                    "name_en": "Warm/Kind",
                    "confidence": 0.84,
                    "source_label": "warm",
                    "mapped": False,
                },
            ],
            "dominant": tag_mood,
            "valence": 0.3,
            "energy": 0.45,
            "reason": "柔和铺底与稳定的低频脉冲。",
        },
        "bpm_key": {
            "bpm": 96,
            "bpm_confidence": 0.8,
            "key": "G",
            "mode": "major",
            "time_signature": "4/4",
            "groove": "稳定的四拍脉冲",
            "notes": "估计值",
        },
        "instruments": {
            "primary": [
                {
                    "id": "instrument-108",
                    "name_zh": "合成器和弦垫底",
                    "name_en": "Synth_Pad",
                    "confidence": 0.88,
                    "source_label": "synth pad",
                    "mapped": False,
                }
            ],
            "secondary": [
                {
                    "id": "instrument-106",
                    "name_zh": "合成拨弦声",
                    "name_en": "Synth_Pluck",
                    "confidence": 0.72,
                    "source_label": "arp",
                    "mapped": False,
                }
            ],
            "notes": "合成器音色为主。",
        },
        "structure": {
            "sections": [
                {"label": "Intro", "label_zh": "前奏", "start_sec": 0, "end_sec": 8, "energy": 0.25, "confidence": 0.7, "description": "铺底"},
                {"label": "Build-up", "label_zh": "推进段", "start_sec": 8, "end_sec": 16, "energy": 0.55, "confidence": 0.7, "description": "脉冲加入"},
                {"label": "Drop", "label_zh": "爆发段", "start_sec": 16, "end_sec": 24, "energy": 0.8, "confidence": 0.7, "description": "主要律动"},
                {"label": "Outro", "label_zh": "尾奏", "start_sec": 24, "end_sec": 28, "energy": 0.3, "confidence": 0.65, "description": "淡出"},
            ],
            "notes": "按能量变化划分。",
        },
        "unmapped": [
            {"category": "Genre", "source_label": "Organic House", "reason": "目录中没有可靠近义标签。"}
        ],
    }
    return {
        "id": "mock",
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
    }
