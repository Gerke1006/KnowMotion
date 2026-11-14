# Manim 排版

场景生成阶段通过 `renderers.latex.render_latex_svg` 编译真实 LaTeX，生成 PDF 后转换为字形轮廓 SVG。公式 SVG 随生成的 `.py` 场景源码保存在 `latex/` 中；Manim 使用 `SVGMobject` 显示，缺少编译器时明确失败，不回退为纯文本。

`math.formula` 使用 `parameters.latex`。导数的分式、积分符号、求和、上下标和勾股公式也使用 LaTeX。连续变化的小数值使用 Times New Roman，避免动画每一帧启动 TeX 编译器。

- 中文标题、说明：宋体（`SimSun`）。
- 英文正文和变化的数值：`Times New Roman`。
- 字幕：`Microsoft YaHei` Bold，白字、深蓝紫色描边，按照参考截图的粗黑体效果匹配。单张截图无法可靠确认原字体文件，所以字体名称、字重、颜色和描边均可配置。

字幕按照实际配音时长分页，长于配音的画面停留保留最后一页。分页依据字符比例估算，未声称逐字精确对齐。
