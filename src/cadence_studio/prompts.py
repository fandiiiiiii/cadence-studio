"""Prompt construction for the audio model and the normalizing LLM."""

from __future__ import annotations

import json
from typing import Any

from .modules import JSON_CONTRACTS, TAG_CONTRACT, BatchSpec
from .taxonomy import Taxonomy, get_taxonomy

AUDIO_SYSTEM_NOTE = (
    "你是一台专业音乐审听工作站。请只根据实际听到的声音判断，不要猜测文件名、艺人或版权信息。"
    "使用清晰的分段文本，给出可复核的细节与必要的保留意见。"
)


def _duration_label(duration: float | None) -> str:
    if not duration:
        return "未知"
    minutes, seconds = divmod(int(round(duration)), 60)
    return f"{minutes} 分 {seconds:02d} 秒"


def build_audio_prompt(
    spec: BatchSpec | dict[str, Any],
    metadata: dict[str, Any] | None = None,
    taxonomy: Taxonomy | None = None,
) -> str:
    spec = spec if isinstance(spec, BatchSpec) else BatchSpec.model_validate(spec)
    metadata = metadata or {}
    tasks: list[str] = []
    if "caption" in spec.modules:
        length = {"short": "2–3 句", "medium": "4–6 句", "long": "8–12 句"}[spec.caption_length]
        tasks.append(
            f"【描述】用{length}写一段完整的音乐描述，覆盖风格、氛围、编曲、人声、制作质感与情绪走向；避免空泛形容词和标签堆砌。"
        )
    if "genre" in spec.modules:
        tasks.append("【曲风】主曲风与最多 3 个次曲风；说明融合元素与判断依据。若风格模糊，给出最接近的描述。")
    if "mood" in spec.modules:
        tasks.append("【情绪】主要情绪、能量强弱、情绪效价（负向到正向）与动态变化。")
    if "bpm_key" in spec.modules:
        tasks.append("【速度与调性】BPM（如无法精确请给范围）、拍号、调性、调式与律动特征。")
    if "instruments" in spec.modules:
        tasks.append("【乐器】主奏乐器、伴奏乐器、合成器/音效与人声织体；标注突出程度。")
    if "structure" in spec.modules:
        detail = "精确到段落与短结构" if spec.structure_detail == "fine" else "主要段落"
        tasks.append(
            f"【结构】{detail}；给出每段起止秒数、英文与中文段落名、能量变化与功能。"
            "段落名使用 Intro / Verse / Pre-Chorus / Chorus / Post-Chorus / Interlude / Bridge / "
            "Instrumental / Breakdown / Build-up / Drop / Outro / Silence / Spoken / Applause / Noise。"
        )
    if "scene" in spec.modules:
        tasks.append("【场景】内容主题、适合的视频/活动/空间/季节场景；区分“音乐本身”与“适合被用在哪里”。")
    if "vocal" in spec.modules:
        tasks.append("【人声】有无、性别、音色、唱法、和声与说唱/吟唱等形态；纯音乐请明确说明。")
    if "language" in spec.modules:
        tasks.append("【语言】演唱或对白的主要语言/方言；多语种与纯音乐请明确。")
    if "lyrics" in spec.modules:
        timestamp_note = "尽量给出每段起止时间。" if spec.lyrics_timestamps else "只需按段落顺序转写，不必逐行时间戳。"
        tasks.append(f"【歌词】听写歌词，听不清处标 [inaudible]；{timestamp_note}同时说明显式内容。")
    if "production" in spec.modules:
        tasks.append("【制作】年代感、制作风格、混音空间、动态处理与音色设计。")
    if "quality" in spec.modules:
        tasks.append("【质量】音质、削波、噪声、失真、完整性、是否适合作为标注成品；给出 0–100 分。")
    if "safety" in spec.modules:
        tasks.append("【安全】是否含露骨性内容、暴力、仇恨、自伤或药物内容；只描述可听出的证据。")
    if "extra" in spec.modules:
        tasks.append("【补充】现场感、ACG、Lo-fi、土味、广场舞等补充属性。")
    if "custom" in spec.modules and spec.custom_instruction.strip():
        tasks.append(f"【自定义要求】{spec.custom_instruction.strip()}")

    meta_lines = []
    if metadata.get("file_name"):
        meta_lines.append(f"文件名：{metadata['file_name']}（不要据此推断内容）")
    if metadata.get("duration_sec"):
        meta_lines.append(f"时长：{_duration_label(metadata['duration_sec'])}")
    meta = "；".join(meta_lines)
    custom_prompt = spec.audio_model_prompt.strip()
    if custom_prompt:
        instruction = custom_prompt
    else:
        instruction = "\n".join(f"{idx}. {task}" for idx, task in enumerate(tasks, 1))
    return (
        f"{AUDIO_SYSTEM_NOTE}\n\n"
        f"请审听整首音频，并只完成以下任务：\n{instruction}\n\n"
        f"{meta}\n"
        "输出要求：使用与任务编号对应的标题；时间点用秒表示；不要输出 JSON，不要添加与听感无关的推测。"
        "如果某项无法判断，直接写明“无法判断”及原因。"
    ).strip()


def _language_instruction(spec: BatchSpec) -> str:
    if spec.language == "en":
        return "除标签标准名外，所有自然语言字段使用英文。"
    if spec.language == "bilingual":
        return "caption.text 使用中文，caption.text_en 使用英文；其余自然语言字段使用中文。"
    return "除标签标准名外，所有自然语言字段使用简体中文。"


def _contract(spec: BatchSpec) -> str:
    lines = []
    for module in spec.modules:
        if module in JSON_CONTRACTS:
            lines.append(f"- {JSON_CONTRACTS[module]}")
    fields = ", ".join(f'"{field}": "..."' for field in spec.custom_fields)
    if "custom" in spec.modules and spec.custom_fields:
        lines.append(f"- custom 必须至少包含字段：{fields}")
    lines.append(
        '- "unmapped": [{"category": "Genre|Mood|...", "source_label": "原始说法", '
        '"closest_hint": "可选", "reason": "为何没有可接受的规范标签"}]'
    )
    return "\n".join(lines)


def build_normalizer_messages(
    spec: BatchSpec | dict[str, Any],
    raw_text: str,
    metadata: dict[str, Any] | None = None,
    *,
    taxonomy: Taxonomy | None = None,
    max_catalog_chars: int = 36000,
    repair_note: str = "",
) -> list[dict[str, str]]:
    spec = spec if isinstance(spec, BatchSpec) else BatchSpec.model_validate(spec)
    taxonomy = taxonomy or get_taxonomy()
    metadata = metadata or {}
    catalog = taxonomy.compact_catalog(spec.modules, max_chars=max_catalog_chars, focus_text=raw_text)
    rules = taxonomy.validation_context(spec.modules)
    custom = ""
    if "custom" in spec.modules:
        custom = (
            "\n自定义要求："
            + spec.custom_instruction.strip()
            + ("\n需要的自定义字段：" + "、".join(spec.custom_fields) if spec.custom_fields else "")
        )
    strict = (
        "只能使用下方目录中的标签 ID。不得发明 ID，不得把不在目录中的标签直接写入结果。"
        if spec.taxonomy_mode == "strict"
        else "优先使用目录标签；确实无法映射时可按原词保留到 unmapped。"
    )
    system = f"""你是 Cadence Studio 的音频标注规范化引擎，负责把音频理解模型的原始观察转换为可入库、可审计的规范 JSON。

## 工作原则
1. 只依据原始观察和曲目元数据，不添加未听出的信息。原始观察出现矛盾时，以更具体的听觉证据为准。
2. 只输出一个合法 JSON 对象，不要 Markdown 代码块，不要解释文字，不要尾随逗号。
3. 只输出本批要求的键：{", ".join(spec.modules)}。不要输出未请求的模块。
4. {strict}
5. 规范标签必须来自目录。若原始标签不在目录中，先按语义（不是字面相似）寻找最接近的标签；例如 Modal Jazz 可能映射到 Cool Jazz，也可能映射到爵士下的其他子类，必须结合听感选择。映射后 source_label 保留原词，mapped=true，并在 reason 说明。找不到可靠映射时放入 unmapped，不要硬塞。
6. 置信度必须诚实：证据弱、风格混合、录音质量差时降低 confidence，不要都写 0.9。
7. 情绪标签遵循互斥规则；曲风允许一个 primary 加少量 secondary；所有标签去重。
8. 数值合法：BPM 20–300；效价 -1–1；能量/置信度 0–1；结构时间 0≤start<end≤时长，按时间排序且尽量不重叠。
9. 音频模型没有给出的时间戳不要凭空编造；结构/歌词时间不确定时给出粗略时间，并降低 confidence。
10. 所有字段内容使用规范、简洁、可检索的表达。{_language_instruction(spec)}

## 输出 JSON 结构
{{
{_contract(spec)}
}}
其中 {TAG_CONTRACT}

## 标签目录（仅这些 ID 有效）
{catalog}

## 规则与约束
{rules}
{custom}
"""
    if repair_note:
        system += f"\n## 修复要求\n上一次输出不符合校验：{repair_note}\n请完整重写合法 JSON。"
    user_payload = {
        "task": "normalize_annotation",
        "requested_modules": spec.modules,
        "taxonomy_version": taxonomy.version,
        "track": {
            "file_name": metadata.get("file_name"),
            "duration_sec": metadata.get("duration_sec"),
            "sample_rate": metadata.get("sample_rate"),
            "channels": metadata.get("channels"),
        },
        "raw_audio_model_output": raw_text,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def prompt_metrics(spec: BatchSpec | dict[str, Any], taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    spec = spec if isinstance(spec, BatchSpec) else BatchSpec.model_validate(spec)
    taxonomy = taxonomy or get_taxonomy()
    catalog = taxonomy.compact_catalog(spec.modules)
    audio = build_audio_prompt(spec)
    rules = taxonomy.validation_context(spec.modules)
    message_chars = len(catalog) + len(rules) + len(build_audio_prompt(spec)) + 2500
    return {
        "audio_prompt_chars": len(audio),
        "catalog_chars": len(catalog),
        "rules_chars": len(rules),
        "normalizer_chars_estimate": message_chars,
        "normalizer_tokens_estimate": int(message_chars / 2.2),
        "taxonomy_tags": sum(
            len(taxonomy.category_tags({"genre": "Genre", "mood": "Mood", "scene": "Scene", "instruments": "Instrument", "vocal": "Vocal", "language": "Language", "extra": "Extra"}[m]))
            for m in spec.modules
            if m in {"genre", "mood", "scene", "instruments", "vocal", "language", "extra"}
        ),
    }
