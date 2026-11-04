# 音乐 / 音频标注任务全景

> 调研日期：2026-11-05。`〔文档〕` 表示有公开来源支持；`〔推断〕` 表示基于多源材料的综合判断。平台未公开的内部标注体系不作事实断言。
>
> 没有任何公开清单可以被证明“穷尽”所有公司的内部工作。本文的目标是给出一个**可扩展的 25 类任务族**，让 Cadence 的字段契约不会漏掉行业里反复出现的工作类型；它不替代特定客户的项目规范。

## 1. 谁在标什么

- **Spotify**〔文档〕：Web API 曾公开 `danceability`, `energy`, `valence`, `acousticness`, `instrumentalness`, `speechiness`, `liveness`, `tempo`, `key`, `mode`, `time_signature`, `loudness` 等 Audio Features，以及 Audio Analysis。2024-11-27 起新接入应用不再能访问这些端点，说明这类听感/结构数据已从公共接口收回为内部资产〔推断〕。来源：[Spotify Web API 变更](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)、[Audio Features](https://developer.spotify.com/documentation/web-api/reference/get-audio-features)。
- **Apple Music**〔文档〕：把元数据分为描述性、表演权/署名、二级元数据；对 mood、genre 等 secondary metadata 明确“少即是多”，不鼓励为多分类而堆砌曲风。来源：[Apple Music metadata](https://artistsupport.cdn-apple.com/support/1119-music-metadata)。
- **YouTube / Google**〔文档〕：Content ID 的核心不是“一首歌一行标签”，而是 asset（composition / recording / music video）+ 分地域所有权与百分比 + reference 指纹 + 嵌入关系（recording 内嵌 composition）+ 权利策略（block / track / monetize）+ 匹配条件（匹配类型、所有权比例、匹配时长）。来源：[YouTube rights management](https://developers.google.com/youtube/partner/rights_management)。
- **TikTok / ByteDance**〔文档 + 推断〕：sound 是一等对象（可复用、有详情页与使用量），商用音乐库面向广告主；公开材料更强调“声音的使用与趋势”，未见公开标注本体〔推断〕。短视频侧常需要“片段 + 用法 + 趋势”，而不只是专辑级标签。来源：[Commercial Music Library](https://ads.tiktok.com/resources/help/article/commercial-music-library)。
- **腾讯系**〔文档〕：腾讯多媒体实验室的智能音乐 API 是腾讯系可核实的任务清单：鼓点、副歌/高潮、结构分析、歌词识别、音准节奏评分、音乐标签（强度/情绪/风格/情感）、四轨音源分离、人声转 MIDI、跳过前奏、听歌识曲。这不等于 TME 内部 schema〔推断〕。来源：[智能音乐能力简介](https://multimedia.tencent.com/zh/docs/smart-music/about/introduction/)。
- **网易云音乐**〔文档〕：对音乐人公开 27 个曲风标签、11 个场景标签、15 个情绪标签（6 正向 / 5 中性 / 4 负向），逐条给出定义、判定依据与示例曲目；场景标签甚至写入 BPM 阈值（如助眠 bpm<90、驾车 bpm>90）。这是“标签必须带可判定规则”的最佳公开范例。来源：[曲风](https://music.163.com/topic?id=53666538)、[场景](https://music.163.com/topic?id=81146808)、[情绪](https://music.163.com/topic?id=81155804)。
- **三大唱片 / 版权侧**〔文档〕：交付走 DDEX ERN，非核心营销元数据走 MEAD，主体识别走 PIE；经销商 style guide 把署名角色（primary / featuring / remixer / composer / conductor…）、explicit 标记、歌词语言、primary genre、版本信息、音频规格（WAV 44.1kHz/16bit/2ch，2s–60min）写成可校验条目。来源：[DDEX Standards](https://ddex.net/standards/)、[Revelator style guide](https://docs.revelator.com/pro/resources/metadata-styleguide)。
- **标注供应商**〔文档〕：Cyanite 一类商业 API 的检索维度即 bpm、genre、subgenre、mood、moodAdvanced、instrument、key、voice、character，另有 playlist matching。Gracenote 等提供音乐描述符与识别服务。来源：[Cyanite API](https://api-docs.cyanite.ai/docs/graphql/inputs/experimental-similar-tracks-filter/)。

## 2. 标准、数据集与本体

- **MusicBrainz**〔文档〕：13 类主实体（artist、recording、release、release group、work、label、area、place、event、series、instrument、genre、url）+ 标签/评分/关系表 + ISRC/ISWC、ISNI/IPI，即“标识符 + 署名关系 + 众包标签”三件套。来源：[Schema](https://musicbrainz.org/doc/MusicBrainz_Database/Schema)。
- **AcousticBrainz**〔文档〕：两层数据——低层（响度、动态、频谱、BPM、调性与音阶）与高层（情绪、曲风、人声、音乐类型，由分类器推断，含 danceability）。来源：[Data](https://acousticbrainz.org/data)。
- **MTG-Jamendo**〔文档〕：5.5 万+ 全曲、195 个标签，仅三大类：genre、instrument、mood/theme。来源：[Zenodo](https://zenodo.org/records/3826813)。
- **MusicCaps**〔文档〕：5.5k 条“音乐—文本”对，描述由人类专家撰写，是 caption 任务基准。来源：[MusicLM 论文](https://arxiv.org/abs/2301.11325)。
- **AudioSet**〔文档〕：声音事件本体，Music 分支下含乐器、曲风、音乐概念、音乐角色、音乐情绪。来源：[AudioSet Ontology](https://research.google.com/audioset/ontology/index.html)。
- **FMA**〔文档〕：106,574 首、16,341 位艺人、161 个层级曲风。来源：[FMA 论文](https://arxiv.org/abs/1612.01840)。
- **Music4All(-Onion)**〔文档〕：109,269 首、26 类音频/视频/元数据特征 + Last.fm 标签与收听记录。来源：[Zenodo](https://zenodo.org/records/6609677)。
- **DDEX / 标识符**〔文档〕：ERN 管核心供应链；MEAD 支持 30+ 种非核心机制（focus track、乐评、歌词、昵称、榜单史、古典细分）；PIE 管主体。ISRC 标识录音与 MV（12 位，1.5 亿+ 已注册，不标识作品与表演者），ISWC 标识作品，EIDR 标识影视标题与版本。来源：[DDEX](https://ddex.net/standards/)、[ISRC](https://isrc.ifpi.org/)、[ISWC](https://www.iswc.org/)、[EIDR](https://www.eidr.org/)。

## 3. 25 类任务族

| # | 任务族 | 标注对象 | 主要用途 | 自动化 | 公开数据 |
| --- | --- | --- | --- | --- | --- |
| 1 | 核心描述元数据 | 标题/艺人/版本/厂牌/日期 | 检索、分账、去重 | 半 | 强 |
| 2 | 自由文本 caption | 音色+编制+氛围+情绪走向 | 生成式检索、冷启动 | 人/半 | 弱（MusicCaps 仅 5.5k） |
| 3 | 曲风/子曲风 | 层级、单/多选、融合 | 推荐、相似、榜单 | 半 | 强 |
| 4 | 情绪/情感 | 正/中/负、细粒度情绪 | 情境歌单、电台 | 半 | 强 |
| 5 | 场景/用途 | 助眠/驾车/学习/健身/广告 | 场景歌单、BGM 选曲 | 半 | 中 |
| 6 | 乐器/编制 | 乐器清单、主奏、编制 | 版权库检索、sync | 半 | 强 |
| 7 | 人声特征 | 有无 vocal、性别、音色、唱法 | 推荐、K 歌、翻唱匹配 | 半 | 中 |
| 8 | 语言/方言 | 歌词语言、方言、双语 | 地域分发、字幕 | 高 | 中 |
| 9 | 歌词转写与对齐 | 逐字/逐句时间戳 | 歌词卡、K 歌、搜索 | 半 | 中 |
| 10 | 结构/段落 | intro/verse/chorus、副歌区间 | 剪辑、高潮、跳前奏 | 半 | 弱 |
| 11 | 节奏 | BPM、拍点、小节、强拍 | DJ、运动、卡点 | 高 | 强 |
| 12 | 调性 | key、mode、Camelot | 混音、和声推荐 | 高 | 中 |
| 13 | 和弦/和声 | 和弦序列、调内进行 | 教学、生成、翻唱 | 高 | 弱 |
| 14 | 听感标量 | energy/danceability/valence 0–1 | 排序、相似 | 高 | 中 |
| 15 | 制作/音质 | 录音室/现场、伴奏、lo-fi、响度 | 品控、场景匹配 | 半 | 弱 |
| 16 | 年代/地域/文化 | 发行年代、地区、文化圈 | 怀旧、地域运营 | 半 | 中 |
| 17 | 相似/影响溯源 | 相似曲、影响源、风格源流 | 推荐、A&R | 半 | 弱 |
| 18 | 显式与安全 | explicit、敏感主题、封面合规 | 合规、未成年人保护 | 半 | 中 |
| 19 | 权利与署名 | 词曲/录音权利、角色、分成、地域、期限 | 结算、claim、授权 | 人 | 弱 |
| 20 | 版本/改编关系 | cover/remix/sample/interpolation | 去重、分账、claim | 半 | 中 |
| 21 | 交付质检 | 通过/退回、退回码、证据 | 上架效率、供应商管理 | 半 | 无 |
| 22 | 受众/人群 | 目标人群、年龄/性别倾向 | 投放、冷启动 | 半 | 无 |
| 23 | 歌单/编辑适配 | 适配歌单、情绪曲线位次 | 编辑运营、自动编排 | 人 | 无 |
| 24 | 同步授权（sync） | 使用类型、媒体、期限、地域、预算档 | 报价与清权 | 人 | 弱 |
| 25 | 非音乐声音事件 | 音效/环境声类别 | 音效库、影视配乐 | 高 | 强 |

## 4. 人工密集 vs 可自动化

可自动化程度大致取决于“是否存在客观参照”：

- **高**：BPM、调性、拍点、响度、音源分离、语种识别、声音事件。
- **半自动**：曲风、情绪、场景、编制——模型预标 + 人工只判例外，是成本和质量的折中点。
- **以人为主**：caption、权利署名、歌单适配、sync、退回原因、受众判断。

公开数据与平台需求存在结构性错位。公开集几乎都是“片段级、单曲级、标签级”（Jamendo 195 标签、FMA 161 曲风、AudioSet 事件类），而平台真正需要的是“曲目级 + 版本级 + 地域级 + 段级时间轴 + 关系图”。caption 只有 MusicCaps 5.5k；结构时间轴、歌词对齐、权利与署名、退回原因、受众、歌单适配在公开集中基本空白〔推断〕。结论：公开数据足以训练“标签与音频特征”，但无法验证“权利、质检、编辑判断”——后者恰是平台最贵的部分。

## 5. Cadence 已覆盖 / 未覆盖

已覆盖（见 [字段契约](annotation-schema.md)）：

- caption、曲风、情绪、场景、乐器、人声、语言、BPM/调性、结构、歌词、制作、质量、安全、补充标签、自定义 JSON；
- 原始模型文本与规范化 JSON 双轨；
- 标签版本、批次快照、人工复核状态。

未覆盖（需要专门的实体/关系模型，不应硬塞进标签字段）：

- 权利与署名、分地域所有权和百分比；
- cover/remix/sample/interpolation 的关系图；
- DDEX/ERN 交付、ISRC/ISWC/EIDR 标识符体系；
- 歌单编排、受众定向、sync 报价；
- 交付质检的退回码树与证据附件；
- 音源分离、MIDI、节拍网格等专用音频任务（可由独立工具补充）。

这些是 Cadence 的**边界**，不是“已实现”。如果未来接入，建议按“实体—描述—关系”三层扩展，不要继续堆在一张 items 表中。

## 6. 对产品 schema 的启示

1. **三层分离**：实体（work / recording / release / party / asset）—描述（可配置本体）—关系（cover / remix / sample / embedding）。权利与署名属于实体与关系层，不要塞进标签字段。
2. **先定值类型**：分类（层级、单选/多选）、标量（0–1、BPM、key/mode）、时间区间（段落、拍点、歌词）、自由文本（caption、QC 备注）、枚举码（退回原因）。五类混在一张表里必然失控。
3. **标签要带“定义 + 正例 + 反例 + 可判定规则”**。网易云把 BPM 阈值写进场景定义；缺少可判定规则，跨标注员一致性无法度量，也无法训练模型。
4. **时间轴与置信度是一等公民**：segment 需 start/end、层级、置信度、标注者、模型版本。
5. **多值维度原生支持**：地域、权利百分比、期限、多语言、多曲风；同一 recording 可有多个版本策略。
6. **把“质检/退回”做成可统计的负样本体系**（reason code 树 + 证据附件），这是提升上架效率最高杠杆的一类标注，也最常被 schema 遗漏。
7. **记录来源与版本**（human / model / DDEX / imported），支持复核与回滚；“机器预标 + 人工判例外”是成本与质量唯一可行的折中。

## 7. 参考来源

1. [Spotify for Developers：Web API 变更公告（2024-11-27）](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)
2. [Spotify Web API：Get Audio Features](https://developer.spotify.com/documentation/web-api/reference/get-audio-features)
3. [Apple Music for Artists：Music metadata](https://artistsupport.cdn-apple.com/support/1119-music-metadata)
4. [YouTube Content ID API：Rights management](https://developers.google.com/youtube/partner/rights_management)
5. [TikTok：About the Commercial Music Library](https://ads.tiktok.com/resources/help/article/commercial-music-library)
6. [网易音乐人：曲风标签分类详解（27 类）](https://music.163.com/topic?id=53666538)
7. [网易音乐人：场景标签分类详解（11 类）](https://music.163.com/topic?id=81146808)
8. [网易音乐人：情绪标签分类详解（15 类）](https://music.163.com/topic?id=81155804)
9. [腾讯多媒体实验室：智能音乐能力简介](https://multimedia.tencent.com/zh/docs/smart-music/about/introduction/)
10. [MusicBrainz Database / Schema](https://musicbrainz.org/doc/MusicBrainz_Database/Schema)
11. [AcousticBrainz：Data（low-level / high-level）](https://acousticbrainz.org/data)
12. [MTG-Jamendo Dataset（195 tags）](https://zenodo.org/records/3826813)
13. [MusicLM / MusicCaps（5.5k music-text pairs）](https://arxiv.org/abs/2301.11325)
14. [AudioSet Ontology](https://research.google.com/audioset/ontology/index.html)
15. [FMA: A Dataset For Music Analysis](https://arxiv.org/abs/1612.01840)
16. [Music4All-Onion](https://zenodo.org/records/6609677)
17. [DDEX Standards](https://ddex.net/standards/) ｜ [MEAD](https://ddex.net/standards/media-enrichment-and-description/)
18. [ISRC（IFPI 官方）](https://isrc.ifpi.org/) ｜ [ISWC（CISAC）](https://www.iswc.org/) ｜ [EIDR](https://www.eidr.org/)
19. [Cyanite API：检索维度](https://api-docs.cyanite.ai/docs/graphql/inputs/experimental-similar-tracks-filter/)
20. [Revelator：Music Metadata Style Guide](https://docs.revelator.com/pro/resources/metadata-styleguide)
