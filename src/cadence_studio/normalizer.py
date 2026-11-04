"""JSON extraction and deterministic governance of LLM-normalized annotations."""

from __future__ import annotations

import json
import re
from typing import Any

from .modules import BatchSpec
from .taxonomy import Taxonomy, get_taxonomy

MUTUALLY_EXCLUSIVE_MOOD_IDS = {"mood-27", "mood-26", "mood-3", "mood-15", "mood-16"}
CATEGORY_FOR_MODULE = {
    "genre": "Genre",
    "mood": "Mood",
    "scene": "Scene",
    "instruments": "Instrument",
    "vocal": "Vocal",
    "language": "Language",
    "extra": "Extra",
}
MODULE_OUTPUT_KEYS = {
    "caption": "caption",
    "genre": "genre",
    "mood": "mood",
    "bpm_key": "bpm_key",
    "instruments": "instruments",
    "structure": "structure",
    "scene": "scene",
    "vocal": "vocal",
    "language": "language",
    "lyrics": "lyrics",
    "production": "production",
    "quality": "quality",
    "safety": "safety",
    "extra": "extra",
    "custom": "custom",
}


class NormalizationError(ValueError):
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def extract_json(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object, tolerating fences and prose."""
    if not text or not text.strip():
        raise NormalizationError("模型未返回内容")
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    start = candidate.find("{")
    if start < 0:
        raise NormalizationError("模型输出中没有 JSON 对象", raw=text)
    depth = 0
    in_string = False
    escape = False
    end = -1
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        raise NormalizationError("模型输出的 JSON 不完整", raw=text)
    try:
        parsed = json.loads(candidate[start:end])
    except json.JSONDecodeError as exc:
        raise NormalizationError(f"JSON 语法错误：{exc.msg}", raw=text) from exc
    if not isinstance(parsed, dict):
        raise NormalizationError("模型输出不是 JSON 对象", raw=text)
    return parsed


def _as_float(value: Any, default: float = 0.0, low: float = 0.0, high: float = 1.0) -> float:
    if isinstance(value, str):
        value = re.sub(r"[^0-9.\-]", "", value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _confidence(value: Any, default: float = 0.65) -> float:
    return round(_as_float(value, default, 0.0, 1.0), 3)


def _text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).strip()[:limit]


class Normalizer:
    def __init__(self, taxonomy: Taxonomy | None = None):
        self.taxonomy = taxonomy or get_taxonomy()

    def _tag(
        self,
        value: Any,
        category: str,
        *,
        default_confidence: float = 0.65,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        if not value:
            return None
        raw_label = ""
        confidence = default_confidence
        mapped = False
        source_label = ""
        if isinstance(value, dict):
            raw_label = _text(value.get("id") or value.get("name_zh") or value.get("name_en"), 200)
            confidence = _confidence(value.get("confidence"), default_confidence)
            mapped = bool(value.get("mapped", False))
            source_label = _text(value.get("source_label"), 200)
        else:
            raw_label = _text(value, 200)
        tag = self.taxonomy.resolve(raw_label, category)
        if not tag:
            warnings.append(f"{category} 标签无法映射：{raw_label[:80]}")
            return None
        source_label = source_label or raw_label
        if tag["id"] != raw_label and not mapped:
            mapped = True
        return {
            "id": tag["id"],
            "name_zh": tag["zh"],
            "name_en": tag["en"],
            "confidence": confidence,
            "source_label": source_label,
            "mapped": mapped,
        }

    def _tag_list(self, values: Any, category: str, warnings: list[str], limit: int = 8) -> list[dict[str, Any]]:
        if values is None:
            return []
        if isinstance(values, (str, dict)):
            values = [values]
        if not isinstance(values, list):
            warnings.append(f"{category} 字段不是数组，已忽略")
            return []
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in values[: limit * 2]:
            tag = self._tag(value, category, warnings=warnings)
            if tag and tag["id"] not in seen:
                seen.add(tag["id"])
                result.append(tag)
            if len(result) >= limit:
                break
        return result

    def _dedupe_primary(self, primary: dict[str, Any] | None, secondary: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if primary:
            secondary = [tag for tag in secondary if tag["id"] != primary["id"]]
        return primary, secondary

    def validate(
        self,
        payload: dict[str, Any],
        spec: BatchSpec,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        duration = float(metadata.get("duration_sec") or 0)
        warnings: list[str] = []
        output: dict[str, Any] = {}
        for module in spec.modules:
            key = MODULE_OUTPUT_KEYS[module]
            value = payload.get(key)
            if value is None and module == "custom":
                value = payload.get("custom")
            if value is None:
                warnings.append(f"缺少请求模块：{module}")
                continue

            if module == "caption":
                if not isinstance(value, dict):
                    value = {"text": _text(value), "short": ""}
                text = _text(value.get("text"), 6000)
                output["caption"] = {
                    "text": text,
                    "short": _text(value.get("short"), 300),
                    "language": _text(value.get("language"), 20) or ("zh" if spec.language != "en" else "en"),
                }
                if "text_en" in value:
                    output["caption"]["text_en"] = _text(value.get("text_en"), 6000)

            elif module in {"genre", "scene", "extra"}:
                if not isinstance(value, dict):
                    value = {"primary": value}
                category = CATEGORY_FOR_MODULE[module]
                primary = self._tag(value.get("primary"), category, warnings=warnings)
                secondary = self._tag_list(value.get("secondary") or value.get("tags"), category, warnings, 4)
                primary, secondary = self._dedupe_primary(primary, secondary)
                item: dict[str, Any] = {"primary": primary, "secondary": secondary}
                if module == "genre" and isinstance(value.get("fusion"), list):
                    item["fusion"] = [_text(x, 80) for x in value["fusion"][:5] if _text(x)]
                item["reason"] = _text(value.get("reason") or value.get("notes"), 1500)
                output[key] = item

            elif module == "mood":
                if not isinstance(value, dict):
                    value = {"tags": value}
                tags = self._tag_list(value.get("tags") or value.get("primary"), "Mood", warnings, 8)
                tags.sort(key=lambda x: x["confidence"], reverse=True)
                kept: list[dict[str, Any]] = []
                excluded: list[str] = []
                for tag in tags:
                    if tag["id"] in MUTUALLY_EXCLUSIVE_MOOD_IDS and any(
                        existing["id"] in MUTUALLY_EXCLUSIVE_MOOD_IDS for existing in kept
                    ):
                        excluded.append(tag["id"])
                        continue
                    kept.append(tag)
                dominant = self._tag(value.get("dominant"), "Mood", warnings=warnings)
                if dominant and all(tag["id"] != dominant["id"] for tag in kept):
                    kept.insert(0, dominant)
                    if dominant["id"] in MUTUALLY_EXCLUSIVE_MOOD_IDS:
                        filtered: list[dict[str, Any]] = []
                        for tag in kept:
                            if tag["id"] in MUTUALLY_EXCLUSIVE_MOOD_IDS and any(
                                existing["id"] in MUTUALLY_EXCLUSIVE_MOOD_IDS for existing in filtered
                            ):
                                excluded.append(tag["id"])
                                continue
                            filtered.append(tag)
                        kept = filtered
                if excluded:
                    warnings.append("按情绪互斥规则移除：" + ", ".join(dict.fromkeys(excluded)))
                dominant = dominant if dominant and any(tag["id"] == dominant["id"] for tag in kept) else (kept[0] if kept else None)
                output["mood"] = {
                    "tags": kept,
                    "dominant": dominant,
                    "valence": round(_as_float(value.get("valence"), 0.0, -1.0, 1.0), 3),
                    "energy": round(_as_float(value.get("energy"), 0.5, 0.0, 1.0), 3),
                    "reason": _text(value.get("reason"), 1500),
                }

            elif module == "instruments":
                if not isinstance(value, dict):
                    value = {"primary": value}
                primary = self._tag_list(value.get("primary"), "Instrument", warnings, 6)
                secondary = self._tag_list(value.get("secondary") or value.get("tags"), "Instrument", warnings, 10)
                seen = {tag["id"] for tag in primary}
                secondary = [tag for tag in secondary if tag["id"] not in seen]
                output["instruments"] = {
                    "primary": primary,
                    "secondary": secondary,
                    "notes": _text(value.get("notes"), 1500),
                }

            elif module == "vocal":
                if not isinstance(value, dict):
                    value = {"present": bool(value)}
                lead = value.get("lead") if isinstance(value.get("lead"), dict) else {}
                output["vocal"] = {
                    "present": bool(value.get("present", False)),
                    "tags": self._tag_list(value.get("tags"), "Vocal", warnings, 8),
                    "lead": {
                        "gender": _text(lead.get("gender"), 30) or "unknown",
                        "timbre": _text(lead.get("timbre"), 300),
                        "delivery": _text(lead.get("delivery"), 300),
                    },
                    "notes": _text(value.get("notes"), 1200),
                }

            elif module == "language":
                if not isinstance(value, dict):
                    value = {"primary": value}
                primary = self._tag(value.get("primary"), "Language", warnings=warnings)
                secondary = self._tag_list(value.get("secondary"), "Language", warnings, 4)
                if primary:
                    secondary = [tag for tag in secondary if tag["id"] != primary["id"]]
                output["language"] = {
                    "primary": primary,
                    "secondary": secondary,
                    "instrumental": bool(value.get("instrumental", False)),
                    "notes": _text(value.get("notes"), 1200),
                }

            elif module == "bpm_key":
                if not isinstance(value, dict):
                    value = {}
                bpm_raw = value.get("bpm")
                if isinstance(bpm_raw, str):
                    bpm_raw = re.sub(r"[^0-9.]", "", bpm_raw)
                try:
                    bpm = round(float(bpm_raw), 1) if bpm_raw not in (None, "") else None
                except (TypeError, ValueError):
                    bpm = None
                if bpm is not None and not 20 <= bpm <= 300:
                    warnings.append(f"BPM {bpm} 超出范围，已置空")
                    bpm = None
                mode = _text(value.get("mode"), 30).lower() or "unknown"
                if mode not in {"major", "minor", "modal", "unknown"}:
                    mode = "unknown"
                key = _text(value.get("key"), 20)
                if key and not re.fullmatch(r"[A-Ga-g](#|b)?", key):
                    key = ""
                time_signature = _text(value.get("time_signature"), 10)
                if time_signature and not re.fullmatch(r"\d{1,2}/\d{1,2}", time_signature):
                    time_signature = ""
                key_normalized = ""
                if key:
                    key_normalized = key[0].upper() + ("b" if len(key) == 2 and key[1] == "b" else "")
                output["bpm_key"] = {
                    "bpm": bpm,
                    "bpm_confidence": _confidence(value.get("bpm_confidence"), 0.6),
                    "key": key_normalized,
                    "mode": mode,
                    "time_signature": time_signature,
                    "groove": _text(value.get("groove"), 600),
                    "notes": _text(value.get("notes"), 1000),
                }

            elif module == "structure":
                if not isinstance(value, dict):
                    value = {"sections": value}
                sections = []
                for _index, section in enumerate(value.get("sections") or []):
                    if not isinstance(section, dict):
                        continue
                    try:
                        start = float(section.get("start_sec", 0))
                        end = float(section.get("end_sec", 0))
                    except (TypeError, ValueError):
                        continue
                    if duration:
                        start = max(0.0, min(start, duration))
                        end = max(start, min(end, duration))
                    if end <= start:
                        continue
                    label = _text(section.get("label"), 80) or "Section"
                    label_zh = _text(section.get("label_zh"), 80)
                    structure_label = self.taxonomy.structure_label(label)
                    if structure_label:
                        label = structure_label["en"]
                        label_zh = label_zh or structure_label["zh"]
                    sections.append(
                        {
                            "label": label,
                            "label_zh": label_zh,
                            "start_sec": round(start, 2),
                            "end_sec": round(end, 2),
                            "energy": round(_as_float(section.get("energy"), 0.5, 0.0, 1.0), 3),
                            "confidence": _confidence(section.get("confidence"), 0.6),
                            "description": _text(section.get("description"), 800),
                        }
                    )
                sections.sort(key=lambda x: x["start_sec"])
                output["structure"] = {"sections": sections, "notes": _text(value.get("notes"), 1200)}

            elif module == "lyrics":
                if not isinstance(value, dict):
                    value = {"text": _text(value)}
                sections = []
                for section in (value.get("sections") or [])[:30]:
                    if not isinstance(section, dict):
                        continue
                    sections.append(
                        {
                            "label": _text(section.get("label"), 80),
                            "start_sec": None if section.get("start_sec") is None else round(_as_float(section.get("start_sec"), 0, 0, duration or 99999), 2),
                            "end_sec": None if section.get("end_sec") is None else round(_as_float(section.get("end_sec"), 0, 0, duration or 99999), 2),
                            "text": _text(section.get("text"), 4000),
                        }
                    )
                output["lyrics"] = {
                    "present": bool(value.get("present", bool(_text(value.get("text"))))),
                    "language": _text(value.get("language"), 60),
                    "text": _text(value.get("text"), 12000),
                    "explicit": bool(value.get("explicit", False)),
                    "sections": sections,
                    "notes": _text(value.get("notes"), 1000),
                }

            elif module == "production":
                if not isinstance(value, dict):
                    value = {}
                output["production"] = {
                    "era": _text(value.get("era"), 80),
                    "production_style": _text(value.get("production_style"), 400),
                    "mix_character": _text(value.get("mix_character"), 400),
                    "texture": _text(value.get("texture"), 400),
                    "quality_flags": [_text(x, 60) for x in value.get("quality_flags", [])[:10]]
                    if isinstance(value.get("quality_flags"), list)
                    else [],
                }

            elif module == "quality":
                if not isinstance(value, dict):
                    value = {}
                output["quality"] = {
                    "score": round(_as_float(value.get("score"), 60, 0, 100), 1),
                    "usable": bool(value.get("usable", True)),
                    "issues": [_text(x, 120) for x in value.get("issues", [])[:12]]
                    if isinstance(value.get("issues"), list)
                    else [],
                    "notes": _text(value.get("notes"), 1000),
                }

            elif module == "safety":
                if not isinstance(value, dict):
                    value = {}
                flags = value.get("flags", [])
                if not isinstance(flags, list):
                    flags = [flags] if flags else []
                output["safety"] = {
                    "explicit": bool(value.get("explicit", False)),
                    "flags": [_text(x, 40) for x in flags[:10]],
                    "notes": _text(value.get("notes"), 1000),
                }

            elif module == "custom":
                output["custom"] = value if isinstance(value, dict) else {"value": value}

        # Governance: keep only requested keys, attach a traceable envelope.
        cleaned = {key: output[key] for key in [MODULE_OUTPUT_KEYS[m] for m in spec.modules] if key in output}
        unmapped = payload.get("unmapped")
        if isinstance(unmapped, list):
            cleaned["unmapped"] = [item for item in unmapped[:30] if isinstance(item, dict)]
        cleaned["_meta"] = {
            "schema_version": "1.0.0",
            "taxonomy_version": self.taxonomy.version,
            "requested_modules": spec.modules,
            "warnings": warnings,
            "validated": True,
        }
        return cleaned

    def parse_and_validate(
        self,
        text: str,
        spec: BatchSpec,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = extract_json(text)
        return self.validate(payload, spec, metadata)


def result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    """Small denormalized summary used by list views and exports."""
    if not result:
        return {}
    genre = (result.get("genre") or {}).get("primary") or {}
    mood = (result.get("mood") or {}).get("dominant") or {}
    bpm = (result.get("bpm_key") or {}).get("bpm")
    key = (result.get("bpm_key") or {}).get("key")
    mode = (result.get("bpm_key") or {}).get("mode")
    caption = (result.get("caption") or {}).get("short") or (result.get("caption") or {}).get("text", "")[:160]
    return {
        "genre": genre.get("name_zh") or genre.get("name_en") or "",
        "mood": mood.get("name_zh") or mood.get("name_en") or "",
        "bpm": bpm,
        "key": f"{key} {mode}".strip() if key else "",
        "caption": caption,
    }
