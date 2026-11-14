# 渲染与音频

`VideoRenderer(settings).generate(plan, path)` 输出可编辑场景参数和 Manim 源码；同步 `render(plan, path)` 输出 `final.mp4`。

- **Manim**：可信模板生成源码，动态割线逼近切线、黎曼矩形细分、勾股关系。公式通过真实 LaTeX 编译为矢量 SVG，中文使用宋体，英文 Times New Roman。安装项目 `manim` extra，并配置 LaTeX 编译器。
- **Canvas / SVG 适配**：CPU 绘制逐帧二维组件并交给 FFmpeg；`svg` 当前复用此二维适配器，不解析外部 SVG。支持数学图形、时间线、关系/过程图和柱状图。
- **Remotion**：需 `remotion_project`，已安装本地 `@remotion/cli`，入口默认 `src/index.ts`，注册 `KnowledgeScene` composition；props 是 `{scene, metadata}`。项目缺失时报技术错误。
- **Blender**：需 `blender_path` 和受信任的 `blender_template` Python 文件。模板接收 `--manifest ... --output ...`。模型不能提交可执行 Python。

`math.derivative_secant`、`math.integral_riemann` 支持安全数学 AST（`x`、常量、四则、有限幂、sin/cos/exp 等），没有 `eval` 或属性访问。组件参数中只接受可绘制的实数函数；奇点和非法表达式会报错。

MiniMax 使用 HTTP `t2a_v2` 的 hex 响应。官方音色目录确认温润青年 ID 为 `Chinese (Mandarin)_Gentle_Youth`；其他音色名可通过 `get_voice` 精确查询。密钥不写入缓存、生成源码或错误消息。每场景配音按文本/模型/音色缓存；保留原始 MP3，仅修剪首尾静音并导出 PCM，再按实际配音长度安排动画，避免截掉口播或补入冗长静止画面。

课程来源 `demo/live` 与配音开关独立；不再因为使用演示课程而静默禁用旁白。默认继承 `TTS_ENABLED`，CLI `--tts` / `--no-tts` 或 API `tts_enabled` 可覆盖。字幕使用粗黑体白字与深蓝描边，对应用户参考图的视觉效果。

配音进入 FFmpeg 后先作响度归一化（默认 `NARRATION_LUFS=-16`），再与低音量 BGM 合成，避免供应商返回的原始语音电平过低而被音乐盖住。

场景使用 0.30 秒画面叠化。每段配音前后预留半个转场长度，音频在这些静音区的中点拼接，避免两个人声叠加或淡出吞掉尾字。场景时长向上对齐视频帧；最终画面和人声统一以 `PLAYBACK_SPEED=1.15` 加速，`atempo` 保留音高。BGM 最后混入，原曲节奏不变。`composition` 保存叠化重叠后的播放时间轴，`speech` 记录原始时长及首尾静音修剪量。

FFmpeg 统一画幅/帧率/音频格式后拼接，循环铺设低音量 BGM，支持 `scene.audio.effects=[{"path":"...","at":1.2,"volume":0.3}]`，音效文件限制在 `assets/audio` 内。Canvas 和 Manim 均提供随场景时间分页的中文字幕；BGM 默认首尾淡入淡出。`music_timeline` 暂作策划元数据，尚未按多个音乐段自动编曲。多个组件按顺序平分场景时长；动画动作与镜头由模板管理，不执行任意模型动作指令。`scene.extensions.visual_style` 的 background、primary、accent、text 字段控制学科配色。

`effective_storyboard.json` 保存配音驱动的实际场景时长，`render_report.json` 标明实际渲染器、缓存命中及声音是否启用。缓存同时校验模板源码指纹；仅检查进程、文件、时长和最终文件能否解码，无 AI 审片循环。

## 实现依据

- [manim-video](https://github.com/browser-use/video-use/tree/main/skills/manim-video)：先定义教学叙事、图形先于公式、分镜独立渲染、统一视觉层次。
- [motion-showreel](https://github.com/ConardLi/garden-skills/tree/main/skills/motion-showreel)：确定性时间轴、主体关系随解释发生变化、真实旁白时长驱动画面。
- [MiniMax 同步 TTS](https://platform.minimax.io/docs/api-reference/speech-t2a-http)、[官方音色目录](https://github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/references/minimax-voice-catalog.md)。

只参考制作方法，自行实现模板；没有复制参考视频、音频、字体素材。用户明确要求一键直出，因此不引入参考技能的确认步骤与 AI 审片流程。
