"""Taxonomy access, deterministic validation and compact prompt rendering."""

from __future__ import annotations

import difflib
import json
import re
import threading
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import TAXONOMY_VERSION

TAXONOMY_PATH = Path(__file__).resolve().parent / "resources" / "taxonomy.json"

MODULE_CATEGORY = {
    "genre": "Genre",
    "mood": "Mood",
    "scene": "Scene",
    "instruments": "Instrument",
    "vocal": "Vocal",
    "language": "Language",
    "extra": "Extra",
}

CATEGORY_MODULE = {value: key for key, value in MODULE_CATEGORY.items()}


def categories_for_module(module: str) -> list[str]:
    """Supplemental tags travel with Genre by default.

    ``Extra`` is still available as a standalone module, but a genre request
    includes the supplemental genre vocabulary in the normalizer catalog.
    """
    if module == "genre":
        return ["Genre", "Extra"]
    if module == "extra":
        return ["Extra"]
    category = MODULE_CATEGORY.get(module)
    return [category] if category else []

_STRIP_RE = re.compile(r"[\s\-_/·•,，.。:：;；'\"“”‘’()（）\[\]【】]+")


def _norm(value: str) -> str:
    return _STRIP_RE.sub("", (value or "").lower())


class Taxonomy:
    def __init__(self, path: Path = TAXONOMY_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._payload: dict[str, Any] | None = None
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_category: dict[str, list[dict[str, Any]]] = {}
        self._alias_index: dict[tuple[str, str], str] = {}
        self._all_alias_index: dict[str, str] = {}

    @property
    def payload(self) -> dict[str, Any]:
        with self._lock:
            if self._payload is None:
                self.reload()
            assert self._payload is not None
            return self._payload

    def reload(self) -> dict[str, Any]:
        with self._lock:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != TAXONOMY_VERSION:
                # Keep the runtime tolerant of local taxonomy upgrades, but expose the version.
                pass
            self._payload = raw
            self._by_id = {tag["id"]: tag for tag in raw["tags"]}
            by_cat: dict[str, list[dict[str, Any]]] = {}
            alias_index: dict[tuple[str, str], str] = {}
            all_alias: dict[str, str] = {}
            for tag in raw["tags"]:
                by_cat.setdefault(tag["category"], []).append(tag)
                for alias in tag.get("aliases", []) + [tag["zh"], tag["en"], tag["id"]]:
                    key = _norm(alias)
                    if key:
                        alias_index[(tag["category"], key)] = tag["id"]
                        all_alias.setdefault(key, tag["id"])
            self._by_category = by_cat
            self._alias_index = alias_index
            self._all_alias_index = all_alias
            return raw

    @property
    def version(self) -> str:
        return self.payload.get("version", TAXONOMY_VERSION)

    @property
    def categories(self) -> dict[str, dict[str, Any]]:
        return self.payload["categories"]

    @property
    def tags(self) -> list[dict[str, Any]]:
        return self.payload["tags"]

    @property
    def structure_labels(self) -> list[dict[str, Any]]:
        return self.payload["structure"]["labels"]

    def _ensure_loaded(self) -> None:
        if self._payload is None:
            self.reload()

    def get(self, tag_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._by_id.get(tag_id)

    def category_tags(self, category: str) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return self._by_category.get(category, [])

    def hierarchy_for(self, tag_id: str) -> list[dict[str, Any]]:
        """Return the level-1..n lineage for a genre tag.

        Supplemental (Extra) tags are intentionally a one-element lineage;
        they are not forced into a fake Genre parent.
        """
        self._ensure_loaded()
        tag = self._by_id.get(tag_id)
        if not tag or tag["category"] != "Genre":
            return [tag] if tag else []
        lineage_ids = tag.get("genre_lineage") or [tag_id]
        return [self._by_id[item] for item in lineage_ids if item in self._by_id]

    def resolve(self, value: str | dict[str, Any], category: str | None = None, cutoff: float = 0.9) -> dict[str, Any] | None:
        """Resolve an id/name/alias to a canonical tag, without inventing values."""
        self._ensure_loaded()
        if isinstance(value, dict):
            raw_id = str(value.get("id") or "").strip()
            if raw_id and raw_id in self._by_id:
                tag = self._by_id[raw_id]
                if not category or tag["category"] == category:
                    return tag
            value = str(value.get("name_zh") or value.get("name_en") or value.get("name") or "").strip()
        value = str(value or "").strip()
        if not value:
            return None
        if value in self._by_id:
            tag = self._by_id[value]
            return tag if not category or tag["category"] == category else None
        key = _norm(value)
        if category:
            tag_id = self._alias_index.get((category, key))
            if tag_id:
                return self._by_id[tag_id]
            candidates = self.category_tags(category)
        else:
            tag_id = self._all_alias_index.get(key)
            if tag_id:
                return self._by_id[tag_id]
            candidates = self.tags
        lookup = {}
        for tag in candidates:
            for alias in tag.get("aliases", []) + [tag["zh"], tag["en"]]:
                n = _norm(alias)
                if n:
                    lookup[n] = tag
        matches = difflib.get_close_matches(key, list(lookup), n=1, cutoff=cutoff)
        if matches:
            return lookup[matches[0]]
        return None

    def search(self, query: str = "", category: str | None = None, limit: int = 500, offset: int = 0) -> dict[str, Any]:
        query_n = _norm(query)
        items = self.category_tags(category) if category else self.tags
        if query_n:
            scored: list[tuple[int, dict[str, Any]]] = []
            for tag in items:
                haystack = " ".join(
                    [tag["id"], tag["zh"], tag["en"], tag.get("group", ""), tag.get("definition", "")]
                )
                if query_n in _norm(haystack):
                    score = 0 if _norm(tag["zh"]).startswith(query_n) or _norm(tag["en"]).startswith(query_n) else 1
                    scored.append((score, tag))
            items = [tag for _, tag in sorted(scored, key=lambda x: (x[0], x[1]["id"]))]
        total = len(items)
        return {"total": total, "items": items[offset : offset + limit]}

    def summary(self) -> dict[str, Any]:
        payload = self.payload
        return {
            "version": self.version,
            "schema_version": payload["schema_version"],
            "source": payload["source"],
            "categories": payload["categories"],
            "structure_labels": self.structure_labels,
            "field_registry": payload["field_registry"],
            "mood_rule": payload["mood_rule"],
            "rule_count": len(payload.get("rules", [])),
            "formula_count": len(payload.get("formulas", [])),
        }

    def structure_label(self, value: str) -> dict[str, Any] | None:
        key = _norm(value)
        for label in self.structure_labels:
            if key in {_norm(label["id"]), _norm(label["en"]), _norm(label["zh"])}:
                return label
        return None

    @staticmethod
    def tag_line(tag: dict[str, Any]) -> str:
        name = f"{tag['zh']}|{tag['en']}" if tag.get("zh") and tag.get("en") else (tag.get("zh") or tag.get("en"))
        group = f"{{{tag['group']}}}" if tag.get("group") else ""
        return f"{tag['id']}={name}{group}"

    def compact_catalog(
        self,
        modules: Iterable[str],
        max_chars: int = 36000,
        focus_text: str = "",
    ) -> str:
        """Render only requested categories as token-efficient id=name lines.

        Full labels are always included; short definitions are added for tags
        that appear in the audio model's raw output to help disambiguation.
        """
        selected: list[str] = []
        for module in modules:
            for category in categories_for_module(module):
                if category not in selected:
                    selected.append(category)
        focus_ids: set[str] = set()
        if focus_text:
            focus_n = _norm(focus_text)
            for tag in self.tags:
                if _norm(tag["zh"]) in focus_n or _norm(tag["en"]) in focus_n:
                    focus_ids.add(tag["id"])
        blocks: list[str] = []
        budget = max(2000, max_chars)
        for category in selected:
            meta = self.categories[category]
            lines = [f"## {category} / {meta['label_zh']}（{len(self.category_tags(category))}）"]
            for tag in self.category_tags(category):
                line = self.tag_line(tag)
                if category == "Genre":
                    line += f" [L{tag.get('genre_level', 1)}"
                    if tag.get("genre_parent_id"):
                        line += f";parent={tag['genre_parent_id']}"
                    line += "]"
                if tag["id"] in focus_ids and tag.get("definition") and tag["definition"] not in {"—", "-"}:
                    line += f" :: {tag['definition'][:120]}"
                lines.append(line)
            block = "\n".join(lines)
            if sum(len(x) for x in blocks) + len(block) > budget:
                # Metadata still tells the normalizer what category is expected.
                blocks.append(
                    f"## {category} / {meta['label_zh']}（目录过大，已省略部分标签；禁止臆造 ID）"
                )
            else:
                blocks.append(block)
        if "structure" in modules:
            labels = "；".join(f"{x['en']}({x['zh']})" for x in self.structure_labels)
            blocks.append(f"## Structure labels\n{labels}")
        return "\n".join(blocks)

    def validation_context(self, modules: Iterable[str]) -> str:
        pieces = []
        selected = set(modules)
        if "mood" in selected:
            pieces.append(f"情绪规则：{self.payload.get('mood_rule', '')}")
        if selected.intersection({"genre", "mood", "scene"}):
            rules = self.payload.get("rules", [])
            relevant = [r for r in rules if r["id"] in {"tempo", "meter", "key-instruments", "discard", "structure-flex"}]
            if "structure" in selected:
                relevant += [r for r in rules if r["id"] in {"functions", "section-naming", "section-length", "beginning-end", "time-precision", "fill", "break", "hold", "short-timing"}]
            seen = set()
            for rule in relevant:
                if rule["id"] in seen:
                    continue
                seen.add(rule["id"])
                points = " ".join(rule.get("points", [])[:2])
                pieces.append(f"{rule['title']}：{points}")
        return "\n".join(pieces)

    def canonical_payload(self) -> dict[str, Any]:
        """Payload used by the UI taxonomy explorer; never includes hidden data."""
        return self.payload


TAXONOMY = Taxonomy()


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    return TAXONOMY
