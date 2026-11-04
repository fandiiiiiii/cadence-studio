from cadence_studio.modules import BatchSpec
from cadence_studio.normalizer import MUTUALLY_EXCLUSIVE_MOOD_IDS, Normalizer, extract_json, result_summary
from cadence_studio.prompts import build_audio_prompt, build_normalizer_messages, prompt_metrics
from cadence_studio.taxonomy import get_taxonomy


def test_taxonomy_counts_and_version():
    tax = get_taxonomy()
    assert tax.version == "workbench-2026-11-03"
    assert len(tax.tags) == 641
    counts = {category: len(tax.category_tags(category)) for category in tax.categories}
    assert counts == {"Genre": 273, "Mood": 33, "Scene": 103, "Instrument": 136, "Vocal": 45, "Language": 23, "Extra": 28}
    assert tax.category_tags("Genre")[0]["seq"] == 1
    assert tax.category_tags("Scene")[0]["seq"] == 1
    assert tax.get("genre-6")["seq"] == 5


def test_taxonomy_resolve_aliases():
    tax = get_taxonomy()
    assert tax.resolve("Cool Jazz", "Genre")["id"] == "genre-146"
    assert tax.resolve("冷爵士", "Genre")["id"] == "genre-146"
    assert tax.resolve("Modal Jazz", "Genre") is None
    assert tax.resolve("noise that does not exist", "Genre") is None
    assert tax.resolve("chill", "Mood")["id"] == "mood-15"


def test_audio_prompt_is_catalog_light():
    spec = BatchSpec(modules=["caption", "genre", "mood", "bpm_key"])
    prompt = build_audio_prompt(spec, {"file_name": "song.mp3", "duration_sec": 210})
    assert "genre-146" not in prompt
    assert "BPM" in prompt
    assert "song.mp3" in prompt
    assert len(prompt) < 2000


def test_normalizer_prompt_only_requested_catalog():
    spec = BatchSpec(modules=["caption", "genre"], language="zh")
    messages = build_normalizer_messages(spec, "raw audio observation", {"duration_sec": 200})
    system = messages[0]["content"]
    assert "genre-146" in system
    assert "mood-15" not in system
    assert "caption" in system
    assert messages[1]["role"] == "user"


def test_prompt_metrics_shrink_with_modules():
    small = prompt_metrics(BatchSpec(modules=["caption"]))
    large = prompt_metrics(BatchSpec(modules=["caption", "genre", "mood", "scene", "instruments", "vocal", "language", "extra"]))
    assert small["catalog_chars"] == 0
    assert large["catalog_chars"] > small["catalog_chars"]
    assert large["taxonomy_tags"] == 641  # Extra is included in genre, but not double-counted



def test_extract_json_tolerates_fence():
    parsed = extract_json('Here is the result:\n```json\n{"caption": {"text": "hi"}}\n```')
    assert parsed["caption"]["text"] == "hi"


def test_normalize_governs_unknown_tags_and_exclusive_moods():
    tax = get_taxonomy()
    normalizer = Normalizer(tax)
    spec = BatchSpec(modules=["genre", "mood"])
    payload = {
        "genre": {
            "primary": {"id": "genre-146", "name_zh": "冷爵士", "name_en": "Cool Jazz", "confidence": 0.9},
            "secondary": [{"id": "not-real", "name_zh": "Modal Jazz"}],
        },
        "mood": {
            "tags": [
                {"id": "mood-15", "name_zh": "轻松/放松", "confidence": 0.8},
                {"id": "mood-16", "name_zh": "平静", "confidence": 0.9},
            ],
            "dominant": {"id": "mood-15"},
            "valence": 2,
            "energy": -1,
        },
        "caption": {"text": "must be dropped"},
    }
    result = normalizer.validate(payload, spec, {"duration_sec": 200})
    assert "caption" not in result
    assert result["genre"]["primary"]["id"] == "genre-146"
    assert len(result["genre"]["secondary"]) == 0
    assert result["mood"]["valence"] == 1.0
    assert result["mood"]["energy"] == 0.0
    mood_ids = [tag["id"] for tag in result["mood"]["tags"]]
    assert len([m for m in mood_ids if m in MUTUALLY_EXCLUSIVE_MOOD_IDS]) == 1
    assert result["_meta"]["validated"] is True


def test_genre_hierarchy_and_multiple_independent_genres():
    normalizer = Normalizer(get_taxonomy())
    spec = BatchSpec(modules=["genre"])
    payload = {
        "genre": {
            "items": [
                {"id": "genre-6", "source_label": "K-Pop", "confidence": 0.9},
                {"id": "genre-19", "source_label": "City Pop", "confidence": 0.8},
                {"id": "extra-15", "source_label": "Live", "confidence": 0.7},
            ],
            "reason": "音频中同时出现了两种曲风线索。",
        }
    }
    result = normalizer.validate(payload, spec)
    items = result["genre"]["items"]
    assert len(items) == 3
    kpop = next(item for item in items if item["id"] == "genre-6")
    assert kpop["level"] == 2
    assert kpop["parent_id"] == "genre-2"
    assert kpop["path"] == ["Pop", "K-Pop"]
    assert [entry["name_en"] for entry in kpop["hierarchy"]] == ["Pop", "K-Pop"]
    live = next(item for item in items if item["id"] == "extra-15")
    assert live["category"] == "Extra"
    assert live["supplemental"] is True
    assert len(result["genre"]["secondary"]) == 2


def test_audio_prompt_does_not_leak_taxonomy_or_standard_structure_labels():
    spec = BatchSpec(modules=["caption", "genre", "structure", "extra"])
    prompt = build_audio_prompt(spec, {"file_name": "x.mp3", "duration_sec": 240})
    assert "genre-" not in prompt
    assert "Intro" not in prompt
    assert "Chorus" not in prompt
    assert "补充" not in prompt
    assert "主曲风" not in prompt


def test_summary_is_denormalized():
    summary = result_summary(
        {
            "caption": {"short": "demo"},
            "genre": {"primary": {"name_zh": "爵士"}},
            "mood": {"dominant": {"name_zh": "轻松"}},
            "bpm_key": {"bpm": 92, "key": "C", "mode": "major"},
        }
    )
    assert summary == {"genre": "爵士", "mood": "轻松", "bpm": 92, "key": "C major", "caption": "demo"}
