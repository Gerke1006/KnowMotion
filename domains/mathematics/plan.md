# 数学教学规划

先用几何对象表达变化，再给出公式。函数自变量、定义域和极限条件必须明确。图形和公式同色对应。证明与数值例子分开，不能把一个例子称为普遍证明。

教学顺序：直观问题 → 动态对象 → 数学关系 → 应用与边界

专业扩展：formula、coordinate_system、mathematical_objects、transformation、proof_steps

每个场景只推进一个核心关系，先写教学目标和旁白，再写对象起止状态与动画。默认使用共享时长和画幅，不追问用户。演示模式仅覆盖 examples 中人工编写的课程；live 模式必须记录可追溯的资料。不增加 AI 审片、质量评分或反复修订环节。技术检查仅验证 Schema、依赖、进程和产物。

## 真实配音驱动的数学动画 1.0

新 live 数学场景使用 domain=mathematics、renderer=manim，extensions.math_animation_version="1.0"。
每幕恰好一个主组件，只用 math.derivative_secant、math.integral_riemann、math.pythagorean、math.formula。
场景表达方式与讲解顺序根据本次主题独立选择，不照抄任何示例课程。

narration 是配音与字幕共同使用的口语稿。使用普通中文、必要的拉丁字母/数字及常规标点；把数学运算写成读法，如平方、加、减、等于、趋近于、负、分之。不写 LaTeX 命令、美元符号、反引号、Markdown、Unicode 上下标、希腊符号或运算符。画面上的正式数学表达另写在 parameters.latex 或 steps 中，继续使用真实 LaTeX。不要删除数学含义来凑纯文本。

LaTeX 字段必须全部使用 ASCII 字符，数学符号使用反斜杠命令，不直接输入 Unicode 数学符号；现有公式排版不支持中文，包括 \text{...} 内也不得放中文。需要的中文解释放在 parameters.labels 中，并在对应旁白节点显示。公式中的下标和变量使用拉丁字母或受支持的 LaTeX 命令，不把中文说明塞进公式。

animation_sequence 不写绝对秒数。每一项包含：
- id：本幕唯一节点 ID。
- anchor：{quote, occurrence, edge}；quote 是本幕 narration 的逐字片段，occurrence 从 1 计数，edge 为 start 或 end。各节点按原文先后推进且锚点不同。
- visible_parts：本节点可见的子对象 ID 数组，明确替换上一节点。尚未讲到的对象不列入；过时的说明、公式步骤及时移除。开场不能把全部对象放上来。
- actions：{target, kind} 数组，target 必须属于 visible_parts；kind 仅 draw、reveal、transform。同一 target 在同一节点最多一个动作。draw 用于轴、曲线、边、公式的逐步绘制；reveal 用于点或说明出现；transform 用于既有对象的变化。
- motion（可选）：{parameter, to}。导数仅 parameter="dx"，数值在 dx_end 至 dx_start 之间，正数；积分仅 parameter="n"，是 n_start 至 n_end 之间的整数。不需要运动的节点省略，未指定则保持上一状态。motion 表示在本节点内由当前值连续变到 to。
- emphasis（可选）：{target, kind, sfx_id}。target 必须可见；kind 仅 pulse、outline、focus；sfx_id 仅 sfx.tap、sfx.drum、sfx.chime。重要推导和结果使用明显弹动、描边或局部聚焦以及短音效，不能只依靠字幕说明重点；每个关键步骤一次，不让每句都重复敲击。

每个节点从真实配音锚点持续到下一节点，最后到旁白结束。为被讲到的对象分别安排节点；演示其变化时继续保留相关对象。不在旁白尚未涉及时提前显示结果，不靠一次展示全部组件再等待讲解。

组件子对象只使用以下 ID：
- math.derivative_secant：axes、curve、point_a、point_b、secant、tangent、delta、formula。割线移动由 motion.dx 控制，切线 tangent 是独立对象；讲到极限关系时再呈现切线和公式。
- math.integral_riemann：axes、curve、bounds、rectangles、formula。矩形可逐一绘制，细分由 motion.n 控制。
- math.pythagorean：triangle、square_a、square_b、square_c、label_a、label_b、label_c、equation_a、equation_b、result。不要先呈现所有面积关系。
- math.formula：formula；parameters.steps 可提供按真实推导顺序排列的 LaTeX 字符串数组，对应 step_1、step_2 等；parameters.labels 对应 label_1、label_2 等。每拍最多显示一个 step 和一个 label。每步必须由你根据本次内容提供，渲染器不会替你推导。显示下一步时移除前一步，不累积整屏文字。

audio 使用空对象，强调声音只通过节点 emphasis.sfx_id 选择，不填写文件路径或猜测音效秒数。镜头、图形和所有强调动作位于画面中间偏上的主体安全区，底部只保留口语字幕。
