"""Annotation capability registry and request specification."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MODULES: list[dict[str, Any]] = [
    {
        "id": "caption",
        "label_zh": "描述 Caption",
        "label_en": "Caption",
        "group": "内容理解",
        "icon": "caption",
        "default": True,
        "description": "整曲的自然语言描述：氛围、编曲、人声、制作与情绪走向。",
        "cost": "low",
    },
    {
        "id": "genre",
        "label_zh": "曲风 Genre",
        "label_en": "Genre",
        "group": "分类标签",
        "icon": "genre",
        "default": True,
        "description": "主曲风与次曲风，严格映射到 338 个曲风标签。",
        "cost": "medium",
    },
    {
        "id": "mood",
        "label_zh": "情绪 Mood",
        "label_en": "Mood",
        "group": "分类标签",
        "icon": "mood",
        "default": True,
        "description": "情绪标签、效价与能量，执行心情节奏互斥规则。",
        "cost": "medium",
    },
    {
        "id": "bpm_key",
        "label_zh": "速度与调性",
        "label_en": "Tempo & Key",
        "group": "音乐性",
        "icon": "tempo",
        "default": True,
        "description": "BPM、拍号、调式、调性与律动感。",
        "cost": "low",
    },
    {
        "id": "instruments",
        "label_zh": "乐器",
        "label_en": "Instruments",
        "group": "音乐性",
        "icon": "instrument",
        "default": True,
        "description": "主奏与伴奏乐器、音色与声音设计。",
        "cost": "medium",
    },
    {
        "id": "structure",
        "label_zh": "曲式结构",
        "label_en": "Structure",
        "group": "音乐性",
        "icon": "structure",
        "default": False,
        "description": "带时间戳的段落划分、能量与段落功能。",
        "cost": "high",
    },
    {
        "id": "scene",
        "label_zh": "场景与用途",
        "label_en": "Scene & Use case",
        "group": "内容理解",
        "icon": "scene",
        "default": False,
        "description": "内容主题、使用场景、季节、地点与视频适配。",
        "cost": "medium",
    },
    {
        "id": "vocal",
        "label_zh": "人声特征",
        "label_en": "Vocal",
        "group": "人声与语言",
        "icon": "vocal",
        "default": False,
        "description": "人声有无、性别、音色、唱法与和声形态。",
        "cost": "medium",
    },
    {
        "id": "language",
        "label_zh": "语言",
        "label_en": "Language",
        "group": "人声与语言",
        "icon": "language",
        "default": False,
        "description": "主语言、方言、多语种与纯音乐判断。",
        "cost": "low",
    },
    {
        "id": "lyrics",
        "label_zh": "歌词转写",
        "label_en": "Lyrics",
        "group": "人声与语言",
        "icon": "lyrics",
        "default": False,
        "description": "歌词全文与可选时间戳；明确标注语言和显式内容。",
        "cost": "high",
    },
    {
        "id": "production",
        "label_zh": "制作与年代",
        "label_en": "Production",
        "group": "制作与质量",
        "icon": "production",
        "default": False,
        "description": "制作年代、混音质感、空间感与声音设计。",
        "cost": "low",
    },
    {
        "id": "quality",
        "label_zh": "音频质量",
        "label_en": "Quality",
        "group": "制作与质量",
        "icon": "quality",
        "default": False,
        "description": "音质、削波、噪声、完整性、可用性与拒收原因。",
        "cost": "low",
    },
    {
        "id": "safety",
        "label_zh": "内容安全",
        "label_en": "Safety",
        "group": "制作与质量",
        "icon": "shield",
        "default": False,
        "description": "显式内容、暴力、自伤、药物等合规标记。",
        "cost": "low",
    },
    {
        "id": "extra",
        "label_zh": "补充标签",
        "label_en": "Extra tags",
        "group": "分类标签",
        "icon": "tag",
        "default": False,
        "description": "现场、ACG、土味、Lo-fi 等 28 个补充语义标签。",
        "cost": "low",
    },
    {
        "id": "custom",
        "label_zh": "自定义要求",
        "label_en": "Custom",
        "group": "高级",
        "icon": "spark",
        "default": False,
        "description": "按你的额外提示词输出自定义 JSON 字段。",
        "cost": "variable",
    },
]

MODULE_BY_ID = {module["id"]: module for module in MODULES}
DEFAULT_MODULE_IDS = [module["id"] for module in MODULES if module["default"]]
ALL_MODULE_IDS = [module["id"] for module in MODULES]

# Categories that can be rendered from the 741-tag taxonomy.
TAXONOMY_MODULES = {"genre", "mood", "scene", "instruments", "vocal", "language", "extra"}

JSON_CONTRACTS: dict[str, str] = {
    "caption": '"caption": {"text": "字符串，自然且具体，不堆砌标签", "short": "不超过 40 字", "language": "zh|en"}',
    "genre": '"genre": {"items": [GENRE_TAG], "reason": "判断依据"}',
    "mood": '"mood": {"tags": [TAG], "dominant": TAG, "valence": -1.0到1.0, "energy": 0.0到1.0, "reason": "依据"}',
    "scene": '"scene": {"primary": TAG, "secondary": [TAG], "reason": "依据"}',
    "instruments": '"instruments": {"primary": [TAG], "secondary": [TAG], "additional": ["目录外的乐器/音色原始描述"], "notes": "音色与演奏特征"}',
    "vocal": '"vocal": {"present": true|false, "tags": [TAG], "lead": {"gender": "female|male|neutral|unknown", "timbre": "描述", "delivery": "描述"}, "notes": "依据"}',
    "language": '"language": {"primary": TAG, "secondary": [TAG], "instrumental": false, "notes": "依据"}',
    "bpm_key": '"bpm_key": {"bpm": 数字, "bpm_confidence": 0.0到1.0, "key": "C|C#|D|...|B", "mode": "major|minor|modal|unknown", "time_signature": "4/4", "groove": "描述", "notes": "依据"}',
    "structure": '"structure": {"sections": [{"label": "Intro|Verse|Chorus|...", "label_zh": "中文", "start_sec": 数字, "end_sec": 数字, "energy": 0.0到1.0, "confidence": 0.0到1.0, "description": "段落特征"}], "notes": "划分依据"}',
    "lyrics": '"lyrics": {"present": true|false, "language": "语言", "text": "全文；无法听清用 [inaudible]", "explicit": false, "sections": [{"label": "Verse 1", "start_sec": 数字或null, "end_sec": 数字或null, "text": "歌词"}], "notes": "置信度与限制"}',
    "production": '"production": {"era": "年代或时期", "production_style": "制作风格", "mix_character": "混音与空间特征", "texture": "声音质感", "quality_flags": ["标签"]}',
    "quality": '"quality": {"score": 0到100, "usable": true|false, "issues": ["问题"], "notes": "审听备注"}',
    "safety": '"safety": {"explicit": false, "flags": ["sexual|violence|self_harm|drugs|hate|none"], "notes": "依据"}',
    "extra": '"extra": {"tags": [TAG], "notes": "依据"}',
    "custom": '"custom": {"按用户要求定义字段，必须是合法 JSON 对象"}',
}

TAG_CONTRACT = (
    'TAG = {"id": "严格来自目录的 ID，例如 genre-2", '
    '"name_zh": "目录中文名", "name_en": "目录英文名", '
    '"confidence": 0.0到1.0, "source_label": "音频模型原始说法", "mapped": true|false}'
)
GENRE_TAG_CONTRACT = (
    'GENRE_TAG = TAG 加上 "category": "Genre|Extra"。'
    "服务端会自动补全 level / hierarchy / parent_id，你不要编造层级，也不要为了补全层级而额外加入父级曲风。"
    "同一首歌可以输出多个 items；不要因为“只能有一个主曲风”而删减模型听到的曲风。"
    "只列音频模型原始观察或明确听感中出现的曲风；没有证据的父级、子级不要添加。"
)


class BatchSpec(BaseModel):
    modules: list[str] = Field(default_factory=lambda: list(DEFAULT_MODULE_IDS))
    language: Literal["zh", "en", "bilingual"] = "zh"
    caption_length: Literal["short", "medium", "long"] = "medium"
    structure_detail: Literal["sections", "fine"] = "sections"
    lyrics_timestamps: bool = False
    include_confidence: bool = True
    taxonomy_mode: Literal["strict", "open"] = "strict"
    custom_instruction: str = Field(default="", max_length=4000)
    custom_fields: list[str] = Field(default_factory=list)
    audio_model_prompt: str = Field(default="", max_length=4000)
    output_language_note: str = Field(default="", max_length=500)
    project_instruction: str = Field(default="", max_length=12_000)
    project_context: str = Field(default="", max_length=30_000)
    project_files: list[str] = Field(default_factory=list)

    @field_validator("modules")
    @classmethod
    def _modules_valid(cls, values: list[str]) -> list[str]:
        seen: list[str] = []
        for value in values:
            if value not in MODULE_BY_ID:
                raise ValueError(f"未知标注模块：{value}")
            if value not in seen:
                seen.append(value)
        if not seen:
            raise ValueError("至少选择一个标注模块")
        return seen

    @field_validator("custom_fields")
    @classmethod
    def _fields_clean(cls, values: list[str]) -> list[str]:
        return [value.strip()[:80] for value in values if value.strip()][:20]

    @model_validator(mode="after")
    def _custom_rules(self) -> BatchSpec:
        if "custom" in self.modules and not self.custom_instruction.strip() and not self.custom_fields:
            raise ValueError("选择自定义模块时，请填写额外要求或自定义字段")
        if "lyrics" in self.modules and self.language == "en":
            pass
        return self

    def public(self) -> dict[str, Any]:
        return self.model_dump()


def module_catalog() -> list[dict[str, Any]]:
    return MODULES


def compact_spec(spec: BatchSpec | dict[str, Any]) -> dict[str, Any]:
    model = spec if isinstance(spec, BatchSpec) else BatchSpec.model_validate(spec)
    return {
        "modules": model.modules,
        "language": model.language,
        "caption_length": model.caption_length,
        "taxonomy_mode": model.taxonomy_mode,
        "custom_instruction": model.custom_instruction,
        "project_instruction": model.project_instruction,
        "project_files": model.project_files,
    }
