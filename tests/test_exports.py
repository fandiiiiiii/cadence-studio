from cadence_studio.exports import _item_row


def test_export_labels_follow_per_module_language():
    item = {
        "file_name": "x.mp3",
        "normalized": {
            "genre": {
                "items": [
                    {
                        "id": "genre-71",
                        "name_zh": "合成器潮",
                        "name_en": "Synthwave",
                        "level": 3,
                        "path": ["Electronic", "Midtempo", "Synthwave"],
                        "hierarchy": [
                            {"name_zh": "电子", "name_en": "Electronic"},
                            {"name_zh": "中速节奏", "name_en": "Midtempo"},
                            {"name_zh": "合成器潮", "name_en": "Synthwave"},
                        ],
                    }
                ],
                "primary": {"name_zh": "合成器潮", "name_en": "Synthwave"},
            },
            "mood": {
                "tags": [{"name_zh": "温暖", "name_en": "Warm"}],
                "dominant": {"name_zh": "温暖", "name_en": "Warm"},
            },
            "scene": {"primary": {"name_zh": "晨间", "name_en": "Morning"}},
            "instruments": {
                "primary": [{"name_zh": "合成器", "name_en": "Synthesizer"}],
                "additional": ["颗粒感 granular synth"],
            },
        },
        "summary": {"genre": "合成器潮", "genre_en": "Synthwave", "mood": "温暖", "mood_en": "Warm"},
    }
    row = _item_row(item, 1, {"genre": "zh", "mood": "en", "scene": "en", "instruments": "zh"})
    assert row["主曲风（参考）"] == "合成器潮"
    assert row["曲风路径（全部）"] == "电子 › 中速节奏 › 合成器潮"
    assert row["主情绪"] == "Warm"
    assert row["场景"] == "Morning"
    assert row["主奏乐器"] == "合成器"
    assert row["补充乐器/音色"] == "颗粒感 granular synth"
