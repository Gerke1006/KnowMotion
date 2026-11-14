# KnowMotion

**让知识动起来：从一个知识点，生成有讲解、有字幕、有数学动画的视频。**

多学科知识视频自动生产系统。输入一个主题，自动完成学科识别、资料研究、教学与视觉规划、三级素材检索、分镜与场景源码生成、并行渲染和 MP4 导出。运行时只有技术执行检查，没有用户澄清节点、AI 审片、质量评分或反复改稿循环。

## 数学视频制作效果

### 最新成片：《微积分的本质》

下面是 **2026 年 11 月 14 日 15:30（北京时间）** 完成的数学视频，时长约 **1 分 18 秒**。从连续变化的直觉出发，依次展示割线逼近切线、黎曼和逼近积分，以及微积分的应用。讲稿与分镜由项目配置的真实文本模型经过 Agent 管线生成，再由 Manim 渲染数学动画、MiniMax 合成中文配音、FFmpeg 完成合成。

[![《微积分的本质》四幕实际画面：连续变化、割线与切线、黎曼和、微积分应用](docs/showcase/2026-11-14-calculus/preview.png)](docs/showcase/2026-11-14-calculus/knowmotion-calculus.mp4)

**[观看 / 下载完整视频（MP4，3.43 MB）](https://github.com/Gerke1006/KnowMotion/raw/refs/heads/main/docs/showcase/2026-11-14-calculus/knowmotion-calculus.mp4)** · [查看仓库中的视频文件](docs/showcase/2026-11-14-calculus/knowmotion-calculus.mp4)

画面预览直接截自这份成片。视频中的具体效果包括：

- **导数可视化**：逐步缩小两点间隔，让割线逼近切线，同时展示间隔和斜率的变化。
- **积分可视化**：不断细化黎曼矩形，把“分割、累加、逼近面积”的过程呈现为动画。
- **统一的数学表达**：深色背景、青色函数曲线、金色重点与 LaTeX 公式，搭配清晰的中文字幕。
- **连续的视听节奏**：中文旁白、背景音乐与场景叠化；画面、字幕和人声同步为 1.15 倍速，并保留音高，场景按实际配音长度收尾。

| 项目 | 本次成片 |
|---|---|
| 主题 / 场景 | 微积分的本质 / 4 幕 |
| 时长 / 画面 | 78.03 秒 / 1280 × 720 / 30 fps |
| 视频 / 音频编码 | H.264 / AAC 立体声 |
| 文本模型 | `deepseek-ai/DeepSeek-V4.1-Flash`，4 次实际调用 |
| 配音 | MiniMax `speech-2.8-turbo`，温润青年 |
| 渲染与合成 | Manim + LaTeX + FFmpeg |

该文件是已有完整 `live` 任务的最终混音版本，背景音乐音量为 `0.30`。随片提供 [模型调用记录](docs/showcase/2026-11-14-calculus/model_calls.json)、[Live 技术验收记录](docs/showcase/2026-11-14-calculus/live_acceptance.json)、[媒体检查](docs/showcase/2026-11-14-calculus/media_verification.json) 和 [发布来源与 SHA-256](docs/showcase/2026-11-14-calculus/publication.json)。公开记录仅将本机绝对路径改为项目相对路径，原始记录保留在本地任务目录；视频文件与最终成片逐字节一致。

## 快速运行

推荐 Python 3.12。项目使用 `uv.lock` 固定 Python 依赖。

```powershell
uv sync --all-extras
# 新环境首次设置；已有 .env 时不要覆盖
Copy-Item .env.example .env
# 在 .env 填入 MODEL_BASE_URL、MODEL_NAME、MODEL_API_KEY 和 MINIMAX_API_KEY
uv run --all-extras vibe doctor
uv run --all-extras python scripts/verify_live.py --topic "微积分的本质"
```

只安装轻量依赖也能生成视频：

```powershell
uv sync --extra dev
uv run --extra dev vibe generate "导数" --mode live --renderer canvas --duration 30
```

后续视频验收一律使用 `live`：由项目配置的文本模型通过 Agent 完成学科识别、资料整理和讲稿/分镜生成，再实际调用 MiniMax 与渲染器。`scripts/verify_live.py` 创建全新任务并检查模型调用记录、真实配音、转场、倍速和最终时长，不接受 demo 成片。`demo` 仍保留作离线组件调试，不能作为端到端验收依据。配音默认按 `TTS_ENABLED=true` 使用 MiniMax 温润青年，配置 BGM 后一并混音。

制作一分多钟的短版可运行 `python scripts/verify_live.py --duration 90 --narration-chars 440`。`--narration-chars` 把全片旁白字符预算传给项目 Agent，促使模型生成四幕精简讲稿；实际时长仍以配音和倍速后的成片为准。BGM 继续读取项目 `BGM_PATH`。

历史导演 v2 的独立正式验收使用单独入口：

```powershell
npm ci --prefix renderers/remotion/project
python scripts/verify_history.py --topic "你要解释的历史主题"
```

只提交主题，Agent 根据本轮检索资料生成约 440 字、5–8 段讲稿，再选择通用资源并编排人物和道具动作。生产配置目标为 75–90 秒，实际时长由 MiniMax 配音决定。软件、资源和配置先冻结，运行中不由开发者补写内容；正式失败任务保留错误与证据，不能修讲稿或分镜后恢复成“独立验收通过”。修复通用软件缺陷后需要新构建和新任务。详见 [History Pack v2](docs/HISTORY_PACK.md)。

`canvas` 是确定性二维绘图适配器，以 Pillow 逐帧绘制，经 FFmpeg 编码，不依赖浏览器；`svg` 目前使用相同二维适配器。Manim 是数学主渲染器，使用真实函数曲线、割线到切线、黎曼矩形和几何对象。公式采用真实 LaTeX 编译，通过 PDF 转为矢量 SVG（Manim）或透明 PNG（Canvas），保留分数、积分、上下标等数学排版。缺少编译器会明确报错，不回退为纯文本公式。

本机 LaTeX 工具位于 `.tools/latex/`（不提交 Git）。也可设置 `LATEX_COMPILER_PATH` 指向 Tectonic 或系统 LaTeX 编译器；公式缓存位于 `data/latex-cache/`。首次运行 Tectonic 可能需要下载其 TeX 宏包。

字体分为三个独立配置：普通中文 `CHINESE_FONT=SimSun`（宋体），英文 `ENGLISH_FONT=Times New Roman`，字幕 `SUBTITLE_FONT=Microsoft YaHei`、粗体白字、深蓝描边。字幕依据用户截图匹配视觉效果；仅凭截图无法唯一确定原字体名称。Canvas 对应 `FONT_PATH`、`ENGLISH_FONT_PATH`、`SUBTITLE_FONT_PATH`。Linux/容器需安装对应字体并配置实际路径，不能使用 Windows 字体路径。

## 真实生产配置

在 `.env` 设置以下字段后：

```dotenv
MODEL_BASE_URL=https://api.minimax.cn/v1
MODEL_NAME=MiniMax-M3.1-Flash
MODEL_API_KEY=你的文本模型密钥
MINIMAX_API_KEY=你的语音密钥
MINIMAX_BASE_URL=https://api.minimax.cn
MINIMAX_MODEL=speech-2.8-turbo
MINIMAX_VOICE_ID=Chinese (Mandarin)_Gentle_Youth
TTS_ENABLED=true
BGM_PATH=D:/audio/vibe-bgm.m4a
```

```powershell
uv run --all-extras vibe generate "微积分的本质"
uv run --all-extras vibe status <job_id>
uv run --all-extras vibe resume <job_id>
```

模型网关通过可配置的 Chat Completions 兼容接口调用日常生产模型。上面的模型名仅为当前 MiniMax 接口示例；也可连接自己的小模型服务，不依赖某个固定供应商的 SDK。文本密钥与语音密钥独立配置。密钥不会写入计划、场景源码或错误正文，`.env` 被 Git 忽略。

配音使用“温润青年”。每段只修剪首尾静音，保留句内停顿和完整旁白；场景按实际语音长度收尾，不再补足预估时长造成几秒停顿。默认 `TRANSITION_DURATION=0.30` 秒叠化，语音在转场预留的静音区衔接；`NARRATION_GAP=0.08` 秒控制额外句间间隔（另有帧对齐误差和保留的自然呼吸）。

默认 `PLAYBACK_SPEED=1.15`，画面、字幕、人声在合成时同步加速，FFmpeg `atempo` 保持音高；`TTS_SPEED=1` 避免重复加速。CLI `--speed 1.15`、API `playback_speed: 1.15` 可按任务覆盖。BGM 在倍速后统一混入，保留原曲节奏。请求 duration 是常速讲稿预算，最终长度由真实语音、转场重叠与倍速决定，不会用静止画面硬补到预算。`effective_storyboard.json` 的 scenes 为渲染时长，composition 为最终播放时间轴，包含转场时间和倍速。

BGM 可留空；默认 `BGM_VOLUME=0.30`，可在 `.env` 调整音乐增益。混音保留峰值余量。如果显式指定不存在的文件，任务会报技术错误。音效由场景音频时间轴指定，文件应放到 `assets/audio/`。

Live 研究目前使用 Wikipedia 中英文搜索及正文摘要，保留实际取回的链接和时间；网络不可达或无资料时明确失败。它不是覆盖所有学科的专业检索服务，适合后续加入教材、论文与史料检索适配器。模型计划经 Pydantic 验证，数学函数由受限 AST 解释，模型文本不会作为 Python 直接执行。

历史 v2 另行优先抓取主题匹配的官方史料注册表，保存实际取回的证据、时间和来源。MiniMax 同一次配音返回词级字幕，字幕、对象显隐、动作和音效共同引用真实词时间；缺失词时间会失败，不按文字长度假定对齐。画面和人声仅在 FFmpeg 合成时应用一次 1.15 倍速，BGM 与音效随后按最终时间混入。BGM 保持当前 0.30 增益，不额外自动压低；原创音效记录可核对的起音、峰值、播放起止与素材 SHA-256。

## API 与任务存储

### 本地前端

在已有 Python 环境与 `.env` 配置基础上，先构建页面，再启动同源 API 服务：

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
uv run --all-extras vibe serve
# 浏览器打开 http://127.0.0.1:8000/
```

工作台左侧只保留 New Video、Library 与 History。New Video 仅接受 Prompt，点击右下角 Generate Video 后进入该任务的 History 详情页，显示输入内容、可折叠的真实 Agent 制作流程，以及完成后的视频播放与下载。Library 展示已完成的 live 视频；History 保留生成记录，并支持继续失败任务、复用有效检查点。页面中的封面取自相应成片，不使用演示视频代替真实结果。

右上角“自定义 API”可以配置兼容 Chat Completions 的文本模型 Base URL、模型名与密钥，以及 MiniMax 配音接口。Base URL 填接口基址（例如以 `/v1` 结尾的地址），不要附加 `/chat/completions`。默认读取项目 `.env`；本地服务的自定义设置单独保存在被 Git 忽略的 `data/runtime-api-settings.json`，不会改写 `.env`，重启后仍生效。空密钥表示保留现有值，恢复默认会删除覆盖配置。每个本地任务在开始执行时取得配置快照，因此运行中的任务不受修改影响，尚未开始的排队任务使用更新后的配置。Temporal 模式需通过 worker 环境配置接口，页面不会假装修改远程 worker。

配置接口不回传密钥，密钥不进入任务记录或视频产物，页面也不将其写入浏览器持久存储。若服务设置了 `API_TOKEN`，在自定义 API 弹窗的访问验证入口输入该服务令牌。生成仍使用完整真实 `live` 管线，默认画面、字幕与配音同步为 1.15 倍速。

前端源文件在 `frontend/`，构建产物在 `frontend/dist/`，由 FastAPI 的 `/` 和 `/assets/` 提供。首次构建后再启动服务；修改前端后重新构建并刷新页面。当前前端启动说明针对本地源码目录，单独安装 Python wheel 不会包含前端构建产物。开发时可运行 `npm --prefix frontend run dev`，API 服务仍需运行。

### API

```powershell
uv run --all-extras vibe serve
# http://127.0.0.1:8000/docs
```

```powershell
$body = @{topic='导数'; mode='live'; renderer='manim'; duration=30; playback_speed=1.15} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/jobs -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

| 接口 | 用途 |
|---|---|
| `GET /health` | 服务与执行后端状态 |
| `GET /domains` | 学科包列表 |
| `POST /jobs` | 提交任务，立即返回任务 ID |
| `GET /jobs` | 最近任务 |
| `GET /jobs/{id}` | 阶段、进度、失败原因与产物列表 |
| `POST /jobs/{id}/resume` | 恢复失败任务，沿用任务 ID 与有效检查点；活动或已完成任务返回 409 |
| `GET /jobs/{id}/video` | 下载完成的 MP4 |
| `GET /jobs/{id}/thumbnail` | 由实际成片生成并缓存 JPEG 封面，遵守同样的任务鉴权 |
| `GET /jobs/{id}/artifacts/{name}` | 下载计划、嵌套场景源码等产物 |
| `GET /ui-config` | 页面是否需要服务令牌，仅返回 `requires_auth` 布尔值 |
| `GET /settings/api` | 当前非密钥配置与密钥是否已配置，不返回密钥 |
| `PUT /settings/api` | 保存本地文本模型与 MiniMax API 覆盖配置，空密钥保留原值 |
| `DELETE /settings/api` | 删除覆盖配置，恢复服务启动时的 `.env` 默认值 |

本地使用 SQLite 和有并发上限的任务队列，API 重启后恢复未完成任务。**本地后端运行一个 API 进程**，用 `LOCAL_WORKERS` 设置内部并发。多 API 进程、多台 worker 使用 Temporal + PostgreSQL。远程服务可设置 `API_TOKEN`，客户端发送 `Authorization: Bearer ...`。

每个任务有独立输出目录；每阶段原子写入 JSON 检查点。恢复时复用有效中间产物，上游检查点损坏则重做其下游计划。场景视频和语音按内容指纹缓存，渲染缓存包含组件源码指纹。共享目录中的任务锁防止重复渲染同时写入；CLI `resume` 适用于已停止/失败的任务。

以上恢复行为用于普通任务。历史 v2 的正式独立验收同时检查冻结清单与产物指纹；正式失败记录不能通过外部修改内容再恢复。软件修复与下一次正式验收分开记录，保留原失败任务。

## Temporal / PostgreSQL / MinIO

```powershell
docker compose up --build
```

Compose 提供本地联调栈：PostgreSQL、持久化 Temporal 开发服务器、MinIO、API、worker。API 默认 `localhost:8000`，Temporal UI `localhost:8233`，MinIO 控制台 `localhost:9001`。此配置使用开发服务与本地默认账号，不能直接当作公网生产部署。

也可连接现有服务：

```dotenv
EXECUTION_BACKEND=temporal
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/vibe
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=vibe-video
```

```powershell
uv run --all-extras python -m workflows.worker
```

Temporal 的工作流调度可恢复的生产 activity，定期 heartbeat，失败时只做有限次数技术重试。所有 worker 与 API 需共享同一 `OUTPUT_DIR`。`storage/artifacts.py` 提供 Local/S3/MinIO 上传、下载、签名链接适配器；主流水线当前使用共享本地存储，未自动把所有产物归档至 S3。MinIO 桶需自行创建，S3 适配器使用 boto3 标准 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` 环境变量。

## 产物与结构

```text
harness/        配置、模型网关、Schema、素材检索、六阶段编排、CLI
domains/        六学科教学规范、风格、组件元数据与演示课
assets/         统一素材目录、来源与许可信息
renderers/      Manim、二维绘图、Remotion、Blender、MiniMax、FFmpeg
workflows/      研究/规划/分镜/生成/渲染阶段、Temporal worker
storage/        SQLite/PostgreSQL 任务库、Local/S3 存储适配器
api/            FastAPI
frontend/       React 前端、液态玻璃导航、任务进度与视频播放
tests/          规划、检索、渲染、网关、存储、任务恢复与 API 测试
```

兼容流程的任务输出 `outputs/<job_id>/`：

```text
video_request.json → research.json → teaching_plan.json → visual_plan.json
→ asset_manifest.json → storyboard.json / video_plan.json
→ scenes/<scene_id>/（可编辑源码、音频、分段视频）
→ effective_storyboard.json → render_report.json → final.mp4
```

历史导演 v2 的核心产物链为：

```text
run_manifest.json → research.json → narration_script.json
→ candidate_resources.json → director_plan.json → speech_manifest.json
→ resolved_timeline.json → director_execution.json → sound_execution.json
→ render_report.json → media_verification.json → live_acceptance.json → final.mp4
```

`calls/` 保留逐次脱敏模型请求与响应；`speech/` 保留原始词时间；`scenes/` 保留 Remotion 参数、帧执行证据和分段视频。`artifact_records.json` 关联各阶段产物与哈希。资源卡、SVG 演员和固定 seed 音效是通用能力，不含特定人物的预写剧情。

素材检索按完整组件、基础组件组合、通用绘图三级执行。场景可拥有不同的 `domain`，分别装载对应 Pack；CLI/API 的 `renderer=auto` 默认保留各场景选择，显式指定其他 renderer 则覆盖全片。优先复用受信组件，通过参数生成源码，不执行模型任意编写的程序。

## 已实现范围与扩展点

数学主流程与二维多学科演示可以本地运行；六学科教学规范、通用 Plan Schema、场景级学科策略、素材索引、真实 MiniMax 配音、FFmpeg 混音和任务管理已实现。History Pack v2 增加了古风纸本演员、骑乘、城门、文书、卷轴、印章与逐拍导演协议，采用真实词时间驱动可见对象和动作。地图使用 Natural Earth 公有领域陆地轮廓与可追溯坐标，只显示当前两个端点；连线表示交流示意，不表示古代国界或精确行程。当前日期与人物符号按旁白逐步显示。旧版地图、时间线、已许可后世人物画仍保留兼容能力。

历史研究优先抓取注册的 UNESCO 丝路资料，并结合通用百科检索；每个历史组件必须引用本次研究取得的来源编号。新增历史主题的机构资料可扩展 `assets/history/sources.json`。来源和坐标校验保证可追溯，不代替历史事实审校。详见 [History Pack](docs/HISTORY_PACK.md)。

Remotion 默认使用内置项目，首次安装 Node 依赖：

```powershell
npm ci --prefix renderers/remotion/project
uv run --all-extras vibe doctor
uv run --all-extras python scripts/verify_history.py --topic "你要解释的历史主题"
```

`REMOTION_PROJECT` 留空即可选择内置项目；也可指向自己的可信项目。默认自动准备 Chrome Headless Shell；已有兼容 Chromium 时可设置 `REMOTION_BROWSER_EXECUTABLE`，浏览器会在付费配音之前检查。`REMOTION_CONCURRENCY=2` 控制单个场景的浏览器并发。输出保留每幕 `.remotion.json` 参数，可编辑源码在 `renderers/remotion/project/src`。Blender 仍需提供模板。运行参数见 [渲染器说明](renderers/README.md)。

## 开发验证

```powershell
uv run --all-extras pytest -q
uv run --all-extras ruff check .
uv run --all-extras vibe doctor
uv run --all-extras python scripts/verify_live.py
```

单元测试检查隔离的代码回归，不能代替真实视频验收。验收会调用配置的付费模型和配音服务，输出 `model_calls.json`（模型、调用时间、响应摘要及用量，不含密钥）与 `live_acceptance.json`。技术失败后可用 `python scripts/verify_live.py --resume <job_id>` 恢复同一 live 任务。Docker 服务仍需单独部署验证。

历史 v2 请使用 `python scripts/verify_history.py --topic "<主题>"`，并遵守上述正式失败保留规则。TypeScript 帧执行审计、音频回归和冻结产物审计属于开发验证；其通过不代表已有正式成片。wheel 包含 v2 资源卡、10 个原创 WAV、Remotion 源码和 `tools/check-director.ts`；Node 依赖、浏览器、系统字体与用户 BGM 需在部署环境准备。

## 参考与设计来源

参考 [video-use/manim-video](https://github.com/browser-use/video-use/tree/main/skills/manim-video) 的先教学规划、逐场景源码与独立渲染、统一视觉风格。参考 [motion-showreel](https://github.com/ConardLi/garden-skills/tree/main/skills/motion-showreel) 的确定性时间轴、连续视觉变化、以实际旁白时长安排画面。按本项目明确要求，未采用它们的人工确认和审片流程。这里的代码与教学样例为本项目实现，并非复制完整上游技能。

历史 v2 还参考 [vibe-knowledge 固定提交 c3a13a8](https://github.com/andyhuo520/vibe-knowledge/tree/c3a13a85f7cc560e5d396f063baecea4b2748e1e) 的旁白锚点、物件入退场和音效峰值定位机制。保留其 [MIT LICENSE 与归属说明](third_party/vibe-knowledge/NOTICE.md)；本项目 SVG 与 WAV 为原创，没有引入上游样片、音乐、配音参照、风格墙或其他媒体。继续使用本项目 MiniMax 和用户提供的 BGM。

接口依据：[MiniMax 文本模型](https://platform.minimax.cn/docs/guides/text-generation)、[同步语音 API](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)、[官方音色目录](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/references/minimax-voice-catalog.md)。
