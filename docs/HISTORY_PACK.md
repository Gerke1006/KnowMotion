# History Pack · 导演协议 v2

历史 live 任务使用项目已配置的文本模型，独立完成资料研究、分段讲稿、资源选择和动作分镜，再调用 MiniMax 温润青年、Remotion 与 FFmpeg。模型提交经过验证的数据，不编写可执行 JavaScript。v2 通过人物和道具的入场、行动、交接、展开、落印与退场组织画面，并保留兼容的地图、时间线和人物组件。

视觉参考 [Motion Showreel](https://github.com/ConardLi/garden-skills/blob/main/skills/motion-showreel/README.zh-CN.md) 的确定性帧函数与连续空间承接，以及 [vibe-knowledge 固定版本](https://github.com/andyhuo520/vibe-knowledge/tree/c3a13a85f7cc560e5d396f063baecea4b2748e1e) 的旁白锚点、物件生命周期和音效起音/峰值卡点机制。古风纸本人物、道具和音效由本项目原创实现；上游 MIT 归属与媒体边界见 [NOTICE](../third_party/vibe-knowledge/NOTICE.md)。历史 v2 中文与字幕采用内置 `History Serif`（Adobe Source Han Serif SC Heavy 2.003，字重 900），作为参考图粗宋体风格的近似，不能声称精确识别了截图字体；英文保持 Times New Roman。

历史专用 `production_profile.json.typography` 使用白色字幕、深灰描边（`subtitle_outline_width=1.0`）与 0.18 背景不透明度，减轻字幕底框对画面的遮挡。这些覆盖通过 `history_settings` 返回配置副本，不改变其他学科的字体配置。字体原始字节、官方固定版本、OFL 许可证和 SHA 记录在 `renderers/remotion/project/public/fonts/`；字体二进制与字幕背景不透明度均纳入冻结检查。

## v2 独立正式验收

先完成软件开发、资源准备与隔离回归，再冻结构建。正式入口只接受一个主题：

```powershell
npm ci --prefix renderers/remotion/project
python scripts/verify_history.py --topic "你要解释的历史主题"
```

该入口读取项目配置并创建全新的 live 任务，会调用真实模型与 MiniMax，可能产生服务费用。固定生产配置见 `assets/history/production_profile.json`：1280×720、30 fps、约 440 字、5–8 段、成片目标 75–90 秒，画面与人声统一为 1.15 倍速。实际时长仍由真实配音决定，禁止硬补静止画面。`TTS_SPEED` 保持 1；BGM 读取用户的 `BGM_PATH`，保持当前 `BGM_VOLUME=0.30`，在成片倍速完成后混入，不再变速或自动压低。

正式运行期间不能由开发者修改讲稿、来源、分镜、锚点、配音或时间轴，也不能读取旧成片或 demo 代替本轮生成。技术传输或渲染重试由管线按预算执行；模型对机器可定位的导演协议错误最多进行一次修复，讲稿不变。没有人工审片、人工改稿或 AI 质量评分循环。

历史 API 和正式入口共享配置中的长输出容量：至少 16000 输出 token、600 秒模型等待上限，保留用户配置的模型名称及服务地址。网络失败最多三次尝试；这些数值在任务开始前进入冻结记录，运行中不调整。

**正式任务失败后保留原任务和错误证据，不修内容后恢复为“独立验收通过”。** 若失败暴露通用软件缺陷，先结束该次验收，再在开发阶段修复并回归，冻结新构建后创建新任务。旧版普通任务的 `--resume` 机制不改变此规则。

冻结清单包括构建指纹、非密钥配置、用户 BGM 指纹、模型请求/响应关联和各阶段产物哈希。依赖与系统字体应在冻结前准备；浏览器缓存、Node 依赖缓存及任务输出是派生产物，不作为新的史料或资源写回源码目录。

## 资源、动作与真实时间

`assets/history/animation_resources.json` 提供 6 种环境、12 种视觉资源和 10 种原创音效。演员/道具是受信 SVG；`info.map` 只显示本次研究核实的两个当前端点，`info.timeline` 只显示当前日期，`info.portrait` 是人物符号而非伪造画像。每拍最多三组前景对象、一个焦点、两条短关键词，未来信息按拍揭示。

MiniMax 同一次配音请求开启 `subtitle_type=word`，保存原始字幕与原文 Unicode 字符偏移。字幕和动作锚点使用观测词时间；缺少可靠词时间即明确失败，不把句子按字数均摊成对齐。修剪首尾静音后统一调整时间轴，FFmpeg 仅在合成阶段应用一次 1.15 倍速。音效保持原速，按最终时间绑定其真实起音或峰值，允许自然跨场景收尾。

`tools/build_history_resources.py` 使用标准库与固定 seed 重建全部音效，资源卡记录生成参数、时长、起音、峰值和 SHA-256。只在开发阶段运行重建工具。每分钟音效目标 12–18 次；最终语义画面窗口最长 4 秒，轻微背景漂移不算信息推进。

主要验收证据：

- `run_manifest.json`、`artifact_records.json`：冻结构建、配置与产物来源。
- `model_calls.json`、`calls/*.request.json`、`calls/*.response.json`：真实模型调用、阶段、用量与脱敏请求/响应。
- `research.json`、`narration_script.json`、`candidate_resources.json`、`director_plan.json`：本轮资料、讲稿、资源选择和模型分镜。
- `speech/*/narration.alignment.raw.json`、`narration.alignment.json`、`speech_manifest.json`：同段音频的原始与规范化词时间。
- `resolved_timeline.json`、`director_execution.json`、`scenes/*/frame_execution.json`：锚点、实际帧执行、可见组与语义节奏。
- `sound_execution.json`、`audio_mix_report.json`：素材指纹、每次触发、截样、播放起止、峰值和增益。
- `render_report.json`、`media_verification.json`、`live_acceptance.json`、`final.mp4`：成片、技术检查与验收结论。

完整字段约定见 [HISTORY_DIRECTOR_PROTOCOL.md](HISTORY_DIRECTOR_PROTOCOL.md)。隔离单元测试只验证实现，不代表上述独立正式验收已通过。

## 兼容组件数据

| 组件 | 参数 | 语义与限制 |
|---|---|---|
| `history.map` | `locations`、`routes`、可选 `viewport`、`note`、`source_ids` | 2–8 个地点；经纬度有限且位于地图支持范围；路线两端引用地点 id；所有路线为示意，不能冒充精确行程或古代国界。 |
| `history.timeline` | `events`、可选 `range`、`note`、`source_ids` | 2–7 个事件，按数值年排序；公元前年为负数，没有公元 0 年；`range` 包含所有事件。 |
| `history.person` | `name`、`role`、`years`、`facts`、可选 `related`、`portrait_asset`、`source_ids` | 1–4 条事实；年代是字符串，可写活动时期；默认人物姓名符号，不制造拟真历史画像。 |

完整 JSON Schema 位于 `domains/history/components/*.schema.json`，Python 验证入口为 `harness.history.normalize_history_component` / `validate_history_parameters`。标准化返回深拷贝，保留教学阶段的原始数据。

地图地点记录为 `{id,name,lon,lat,year?,description?,source_ids?}`。路线为 `{from,to,label?,kind:"schematic",source_ids?}`，可选 `id` 必须唯一。若提供视窗，格式为 `{west,east,south,north}`，必须包含所有地点；当前不支持跨日期变更线视窗。

时间线事件为 `{year,label,detail?,date_label?,source_ids?}`。对世纪、约数、日期范围或有分歧的纪年，必须提供 `date_label`：例如“约公元前2世纪”或“公元前139/138年（记载有异）”。此时 `year` 只用于布局，画面显示 `date_label`，不把布局锚点当成精确史实。

人物 `related` 记录为 `{name,relation}`，不把关系自动解释成单向因果。`portrait_asset` 只接受已批准素材根目录下的 `portraits/...` 相对图片路径，不接受网址、绝对路径或目录穿越；没有授权画像时留空。

## 来源与地理边界

研究阶段为真实取回的资料分配 `source_01` 等 id，规划阶段要求每个组件有非空 `source_ids`。未知 id 会在渲染前报错；此检查保证引用能追溯，不能代替历史事实的专家审校。嵌套记录可以补充更具体的引用。画面来源说明从 `scene.extensions.historical_sources` 取得资料标题与链接。

`research.geography` 提供 `assets/history/locations.json` 中的近似现代地理坐标。当前目录包含七个丝路相关地点，并用 `topics` 显式限定主题范围；它不是通用历史地名检索器。主题命中目录范围时提供该目录，否则只保留用户主题或本轮研究知识明确提及的地点，且至少两个才向规划器附加地理资料。其他历史主题（例如文艺复兴）没有可靠坐标时使用时间线和人物组件，不借用丝路地点拼凑地图。规划器校验地图地点 id 与经纬度必须匹配本轮资料；坐标的来源、精度说明和用途限制随筛选后的记录保留。

地名目录标明现代定位与历史用途的区别；底图使用陆地形状，不叠现代行政疆界。路线是交流关系示意，不声称从史料复原每段真实路径。v2 由模型依据主题与证据选择资源，没有可靠坐标时不强行加入地图，也不为凑组件覆盖率改变讲稿。

张骞第一次出使年代在当前 UNESCO 资料之间存在公元前 139 / 138 年的差异。应保留来源说明或使用“公元前2世纪”的概括；不静默选择一个精确日期作为无争议定论。

## 兼容与分发

旧 `silk_road.json` 是 Phase 1 的离线教学 fixture，保持 Canvas 兼容，不作为 Phase 2 的验收视频。`domains/build_catalog.py` 在重建旧目录后调用 `domains.history.definition.install_metadata`，恢复 Phase 2 的规则、样式、JSON Schema 与素材注册，避免重建把 Remotion 元数据退回旧版。

Python wheel 包含 v2 资源卡、全部原创 WAV、Remotion 源码与 `tools/check-director.ts`，以及固定上游 MIT 归属；历史专用 Heavy OTF、原版 OFL 与来源清单也一同打包。Node 依赖、浏览器、其余系统字体、用户 BGM 和前端构建另行部署。Docker 构建同时复制字体、资源重建工具和 TypeScript 帧审计工具；其余容器字体由部署配置显式选择，不冒充 Windows 字体。
