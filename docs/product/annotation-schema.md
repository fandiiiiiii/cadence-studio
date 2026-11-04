# 标注字段契约（Annotation Schema v1.1）

本文件是 Cadence Studio 的**产品契约**，不是模型说明书。任何 UI、API、导出或自动化改动都必须遵守这里定义的字段、状态和治理规则。

- 结果 schema：`1.1.0`
- 标签体系：`workbench-2026-11-03`（641 tags / 15 rules / 7 formulas）
- 结构词表：20 个结构标签
- 存储：`items.normalized_json` + `items.raw_text` + `items.llm_raw_text`
- 代码入口：`src/cadence_studio/modules.py`、`normalizer.py`、`prompts.py`

## 1. 15 个标注模块

用户只勾选本次真正需要的模块。**最终 JSON 只包含被勾选的模块键**，不会输出多余字段。

| 模块 ID | 中文 | 输出键 | 标签类别 | 主要约束 |
| --- | --- | --- | --- | --- |
| `caption` | 描述 | `caption` | — | 自然语言；可短/中/长；中英双语可选 |
| `genre` | 曲风 | `genre` | Genre（273）+ Extra（28） | `items` 完整保留所有曲风；每项带一级/二级 path；不强制单个主曲风 |
| `mood` | 情绪 | `mood` | Mood（33） | 多个 tags；互为互斥的 5 个心情节奏标签最多保留 1 个 |
| `scene` | 场景与用途 | `scene` | Scene（103） | 1 个 primary + 最多 4 个 secondary |
| `instruments` | 乐器 | `instruments` | Instrument（136） | 主奏/伴奏分层；去重 |
| `vocal` | 人声特征 | `vocal` | Vocal（45） | 有无、性别、音色、唱法、和声；纯音乐可明确为无 |
| `language` | 语言 | `language` | Language（23） | 主语言 + 次语言；纯器乐标记 |
| `bpm_key` | 速度与调性 | `bpm_key` | — | BPM 20–300；调式枚举；拍号 `n/n`；可空 |
| `structure` | 曲式结构 | `structure` | 结构词表 + 自定义 | 时间区间不重叠、按时间排序、限制在时长内 |
| `lyrics` | 歌词 | `lyrics` | — | 全文/分段；可带时间戳；显式内容标记 |
| `production` | 制作与年代 | `production` | — | 年代、制作风格、混音、质感 |
| `quality` | 音频质量 | `quality` | — | 0–100 分、可用性、问题清单 |
| `safety` | 内容安全 | `safety` | — | explicit + flags + 证据备注 |
| `extra` | 补充标签 | `extra` | Extra（28） | 现场、ACG、土味、Lo-fi 等 |
| `custom` | 自定义 | `custom` | — | 用户提示词 + 自定义字段；必须是 JSON 对象 |

模块定义见 `GET /api/modules`。

### 1.1 两个模型的分工

- **音频模型**只接收原生任务提示：例如“列出所有曲风与更具体的风格”，不接收 641 目录、标签 ID、规则文档或标准结构词表。原因是它的输入上下文有限，且规范映射是文字模型的职责。
- **文字模型**接收音频模型原文 + 本次请求的紧凑目录/规则，输出规范 JSON；服务端再做确定性校验。
- 用户选择 `genre` 时，规范化目录自动包含 `Genre + Extra`；但音频提示中不会额外提醒补充曲风。

## 2. 规范标签对象

所有分类标签统一为：

```json
{
  "id": "genre-146",
  "name_zh": "冷爵士",
  "name_en": "Cool Jazz",
  "confidence": 0.86,
  "source_label": "Modal Jazz",
  "mapped": true
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | **唯一规范值**，必须来自当前标签体系；禁止模型编造 |
| `name_zh` / `name_en` | string | 从目录回填的标准名，防止模型改写 |
| `confidence` | 0–1 | 模型自评；不是校准概率，用于抽样和排序 |
| `source_label` | string | 音频模型或规范化模型的原始说法 |
| `mapped` | bool | 是否发生过语义/近似映射 |

### 近似映射规则

- 规范标签必须来自目录；目录外标签不得直接写入。
- 允许**语义近似**：例如 `Modal Jazz` 可能在具体听感更接近时映射为 `Cool Jazz`，但必须：
  1. 保留 `source_label` 原文；
  2. 设 `mapped: true`；
  3. 在 `reason` 或 `unmapped` 中说明依据；
  4. 置信度反映不确定性。
- 找不到可靠映射时写入根级 `unmapped`，不要硬塞一个近似值。

```json
"unmapped": [
  {
    "category": "Genre",
    "source_label": "Organic House",
    "closest_hint": "Ambient House",
    "reason": "听感更接近氛围电子，不能可靠归入目录中的 Organic House。"
  }
]
```

## 3. 结果示例

请求模块：`caption`, `genre`, `mood`, `bpm_key`, `instruments`, `structure`。

```json
{
  "caption": {
    "text": "一首温暖、克制的晨光电子小品。合成器铺底从远处浮现，随后加入干净的电子脉冲与空气感琶音。整体无人声，情绪从安静逐渐转向明亮。",
    "short": "温暖晨光电子，柔和琶音与轻四拍。",
    "language": "zh"
  },
  "genre": {
    "items": [
      {
        "id": "genre-71",
        "name_zh": "合成器潮",
        "name_en": "Synthwave",
        "category": "Genre",
        "level": 3,
        "path": ["Electronic", "Midtempo", "Synthwave"],
        "hierarchy": [
          {"id": "genre-48", "name_zh": "电子", "name_en": "Electronic", "level": 1},
          {"id": "genre-69", "name_zh": "中速节奏", "name_en": "Midtempo", "level": 2},
          {"id": "genre-71", "name_zh": "合成器潮", "name_en": "Synthwave", "level": 3}
        ],
        "confidence": 0.84,
        "source_label": "synthwave / ambient electronic",
        "mapped": false
      },
      {
        "id": "genre-77",
        "name_zh": "氛围电子",
        "name_en": "Ambient",
        "category": "Genre",
        "level": 2,
        "path": ["Electronic", "Ambient"],
        "hierarchy": [
          {"id": "genre-48", "name_zh": "电子", "name_en": "Electronic", "level": 1},
          {"id": "genre-77", "name_zh": "氛围电子", "name_en": "Ambient", "level": 2}
        ],
        "confidence": 0.78,
        "source_label": "ambient",
        "mapped": false
      }
    ],
    "primary": {
      "id": "genre-71",
      "name_zh": "合成器潮",
      "name_en": "Synthwave",
      "confidence": 0.84,
      "source_label": "synthwave / ambient electronic",
      "mapped": false
    },
    "secondary": [
      {
        "id": "genre-77",
        "name_zh": "氛围电子",
        "name_en": "Ambient",
        "confidence": 0.78,
        "source_label": "ambient",
        "mapped": false
      }
    ],
    "fusion": ["synthwave", "ambient electronic"],
    "reason": "合成器铺底和缓慢展开为主，脉冲与琶音带有 synthwave 色彩。"
  },
  "mood": {
    "tags": [
      {
        "id": "mood-4",
        "name_zh": "温暖/友好的",
        "name_en": "Warm/Kind",
        "confidence": 0.86,
        "source_label": "warm",
        "mapped": false
      },
      {
        "id": "mood-8",
        "name_zh": "鼓舞人心的/希望的",
        "name_en": "Inspirational/Hopeful",
        "confidence": 0.7,
        "source_label": "hopeful",
        "mapped": false
      }
    ],
    "dominant": {
      "id": "mood-4",
      "name_zh": "温暖/友好的",
      "name_en": "Warm/Kind",
      "confidence": 0.86,
      "source_label": "warm",
      "mapped": false
    },
    "valence": 0.35,
    "energy": 0.42,
    "reason": "柔和铺底、稳定低脉冲、逐渐变亮的和声。"
  },
  "bpm_key": {
    "bpm": 96,
    "bpm_confidence": 0.82,
    "key": "G",
    "mode": "major",
    "time_signature": "4/4",
    "groove": "稳定四拍，轻切分",
    "notes": "BPM 为听感估计。"
  },
  "instruments": {
    "primary": [
      {
        "id": "instrument-108",
        "name_zh": "合成器和弦垫底",
        "name_en": "Synth_Pad",
        "confidence": 0.9,
        "source_label": "synth pad",
        "mapped": false
      }
    ],
    "secondary": [
      {
        "id": "instrument-106",
        "name_zh": "合成拨弦声",
        "name_en": "Synth_Pluck",
        "confidence": 0.76,
        "source_label": "arpeggio",
        "mapped": false
      }
    ],
    "notes": "以合成器音色为主，未听出原声乐器。"
  },
  "structure": {
    "sections": [
      {
        "label": "Intro",
        "label_zh": "前奏",
        "start_sec": 0,
        "end_sec": 8,
        "energy": 0.25,
        "confidence": 0.72,
        "description": "合成器铺底建立氛围"
      },
      {
        "label": "Build-up",
        "label_zh": "推进段",
        "start_sec": 8,
        "end_sec": 16,
        "energy": 0.55,
        "confidence": 0.7,
        "description": "电子脉冲与琶音加入"
      },
      {
        "label": "Drop",
        "label_zh": "爆发段",
        "start_sec": 16,
        "end_sec": 24,
        "energy": 0.8,
        "confidence": 0.68,
        "description": "主要律动完整展开"
      },
      {
        "label": "Outro",
        "label_zh": "尾奏",
        "start_sec": 24,
        "end_sec": 28,
        "energy": 0.3,
        "confidence": 0.66,
        "description": "能量衰减"
      }
    ],
    "notes": "按能量变化划分；边界精度未经人工听验。"
  },
  "unmapped": [],
  "_meta": {
    "schema_version": "1.1.0",
    "taxonomy_version": "workbench-2026-11-03",
    "requested_modules": ["caption", "genre", "mood", "bpm_key", "instruments", "structure"],
    "warnings": [],
    "validated": true
  }
}
```

## 4. 各模块字段规则

### caption

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `text` | string | 主描述；按 `caption_length` 控制长度 |
| `short` | string | ≤ 300 字；用于表格预览 |
| `language` | string | `zh` / `en` |
| `text_en` | string? | 仅 `bilingual` 时出现 |

要求具体、可复核，不堆砌标签；不把模型原文直接复制成最终 Caption。

### genre / scene / extra

**genre 是层级数组，不是单选。**

- `items`：音频模型观察到的所有曲风，逐个独立保留；不因为“只能有一个主曲风”而删除。
- 每个 item 由服务端从目录回填：
  - `category`: `Genre` 或 `Extra`；
  - `level`: 1 = 一级曲风，2 = 二级，3 = 三级；
  - `parent_id`: 上一级 ID；
  - `path`: 例如 `["Pop", "K-Pop"]`；
  - `hierarchy`: 从一级到当前级的完整对象数组。
- 示例：K-Pop → `level=2`, `parent_id=genre-2`, `path=["Pop","K-Pop"]`。
- `primary` / `secondary` 只是**展示便利字段**（第一项/其余项），不限制 `items` 数量，也不表示模型只能输出一个主曲风。
- `fusion` 允许自由描述融合风格，不替代 `items`。
- `Extra` 标签默认随 Genre 进入规范化目录；音频模型不会被单独提示“补充曲风”。
- `reason`：解释听感依据，不写营销文案。

**scene / extra** 仍是 `primary` + `secondary` 结构；`extra` 单独请求时使用。

#### 多曲风与补充曲风

```json
{
  "genre": {
    "items": [
      {"id": "genre-6", "category": "Genre", "level": 2, "path": ["Pop", "K-Pop"]},
      {"id": "genre-19", "category": "Genre", "level": 2, "path": ["Pop", "City Pop"]},
      {"id": "extra-15", "category": "Extra", "level": 1, "path": ["Live"], "supplemental": true}
    ],
    "primary": {"id": "genre-6", "name_zh": "韩国流行"},
    "secondary": [{"id": "genre-19"}, {"id": "extra-15"}]
  }
}
```

上面三项都会保留；不会因为有两个 Genre 就把其中一个丢掉。

### mood

- `tags`：按置信度降序，最多 8 个。
- **互斥**：`mood-27 Dynamic/Energetic`、`mood-26 Groovy/Funky`、`mood-3 Brisk/Carefree`、`mood-15 Chill`、`mood-16 Calm/Relaxing` 最多保留 1 个。
- `dominant`：必须是 tags 中的一项（或 `null`）。
- `valence`：-1（负向）到 1（正向）。
- `energy`：0–1。

### instruments

- `primary`：最多 6 个，主奏/最突出。
- `secondary`：最多 10 个，伴奏/织体。
- 同一 ID 不得同时出现在两组。

### vocal

```json
{
  "present": true,
  "tags": [{"id": "vocal-2", "...": "..."}],
  "lead": {"gender": "female", "timbre": "明亮", "delivery": "气声"},
  "notes": "副歌加入和声"
}
```

`present=false` 时不要求空 tags；纯音乐应明确说明。

### language

- `primary`：语言/方言标签或 `null`。
- `instrumental=true` 表示无歌词/无人声。
- 多语种可放 `secondary`。

### bpm_key

- `bpm`：20–300，无法判断时为 `null`；允许小数。
- `bpm_confidence`：0–1。
- `key`：`C, C#, Db, D...`；大小写标准化为大写，保留 `b`。
- `mode`：`major` / `minor` / `modal` / `unknown`。
- `time_signature`：`4/4`、`3/4`、`6/8`；不合法时置空。
- 渐变/自由速度时用 `notes` 说明。

### structure

- `sections` 按 `start_sec` 升序。
- `0 ≤ start_sec < end_sec ≤ duration`；越界由服务端裁剪。
- 结构标签优先映射 20 个标准词：Intro, Verse, Pre-Chorus, Chorus, Post-Chorus, Interlude, Bridge, Instrumental, Breakdown, Build-up, Drop, Outro, Silence, Spoken, Applause, Noise, Fill, Break, Hold, End。
- 允许自定义 `label`，但需保留 `label_zh` 和描述。
- 不强行把非流行曲式套成 Verse/Chorus。

### lyrics

- `present`、`language`、`text`、`explicit`、`sections`、`notes`。
- 听不清处使用 `[inaudible]`；不要编造歌词。
- `sections[].start_sec/end_sec` 可为 `null`。
- 显式内容只描述可听出的证据，不作道德判断。

### production / quality / safety

- `production`：年代、制作风格、混音空间、质感；不做版权判断。
- `quality.score`：0–100；`usable`；`issues` 数组。
- `safety.flags`：建议枚举 `sexual`, `violence`, `self_harm`, `drugs`, `hate`, `none`；也可保留自由文本。
- 质量/安全字段不替代平台合规审核。

### custom

- 必须由用户提供额外要求或字段。
- 最终 `custom` 必须是 JSON 对象；字段名由用户输入决定。
- 只允许用户明确请求的字段；不得自动扩展。

## 5. 根级字段

| 字段 | 何时出现 | 说明 |
| --- | --- | --- |
| `unmapped` | 有无法映射标签时 | 原词、类别、最近提示、原因 |
| `_meta.schema_version` | 总是 | 当前 `1.1.0` |
| `_meta.taxonomy_version` | 总是 | 批次冻结的标签版本 |
| `_meta.requested_modules` | 总是 | 校验“只请求所需字段” |
| `_meta.warnings` | 可选 | 互斥移除、缺失模块、数值修正等 |
| `_meta.validated` | 总是 | 服务端确定性校验通过 |
| `_meta.manual_edit` | 人工编辑后 | 标记结果被人工修改 |
| `_meta.edited_at` | 人工编辑后 | 编辑时间 |

## 6. 批次快照

每个批次在创建时冻结：

- `spec`：模块、语言、Caption 长度、严格模式、自定义要求；
- `route_snapshot`：音频模型路由 ID/名称/模型、规范化模型路由 ID/名称/模型；
- `taxonomy_version`：通过结果的 `_meta` 写入；
- 创建时间、原始文件名、SHA-256、时长、采样率、声道。

即使之后修改了设置或标签体系，历史批次仍按当时的快照解释。

## 7. 状态词汇

| 层级 | 状态 |
| --- | --- |
| Batch | `draft`, `queued`, `running`, `paused`, `completed`, `completed_with_errors`, `canceled` |
| Item | `queued`, `preprocessing`, `inferencing`, `normalizing`, `saving`, `completed`, `failed`, `canceled` |
| Review | `unreviewed`, `approved`, `needs_changes` |

UI 显示的中文标签仅用于展示；数据库和 API 使用英文枚举。

## 8. 导出契约

- **XLSX**：批次概览、标注总表、原始与规范化、结构时间轴、标签映射。
- **JSON**：批次元数据 + 每项 raw/llm_raw/normalized/timings/error/models。
- **Markdown**：可审阅报告，逐曲包含 Caption、结构化结果与原始观察。
- **CSV**：一行一首，UTF-8 BOM，适合 BI/表格。
- **ZIP**：以上格式 + `taxonomy.json` + manifest。

导出不会包含 API Key。音频文件不默认打包进 ZIP；如需要，请单独归档 `data/audio/{batch_id}/`。
