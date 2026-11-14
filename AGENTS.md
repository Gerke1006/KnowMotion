# Project validation

- 用户要求：之后的视频验收必须使用本项目已配置的文本模型和完整 Agent 管线，先生成文本/分镜，再生成视频。禁止用手写讲稿、demo 样例、mock 模型或复用旧 demo 成片代替端到端验收。
- 运行 `python scripts/verify_live.py`，它读取项目 `.env`，创建新的 live 任务，调用 Orchestrator、真实模型、MiniMax、渲染器与 FFmpeg。技术失败可用 `--resume <job_id>` 恢复同一 live 任务。
- 单元回归可使用隔离 fixture，但不能作为真实视频验收的替代品。交付需说明实际模型与成片，保留 `model_calls.json` 和 `live_acceptance.json`。
- 默认成片速度为常速的 1.15 倍，画面、字幕和人声同步，保留音高。不要通过 TTS_SPEED 再加速一次。
- 场景按实际配音长度收尾，场景之间短叠化，避免按计划时长补入数秒静止或无声等待。
- 不在日志、报告、源码或回复中输出 API 密钥。
