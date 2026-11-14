"""Rebuild the bundled, human-authored demonstration lessons and metadata.

This is a developer utility, never an inference-time content generator.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = {
    "mathematics": {"name": "数学", "style": "geometric_clarity", "keywords": ["数学", "微积分", "导数", "积分", "勾股", "几何", "代数", "概率", "函数", "矩阵", "calculus", "derivative", "integral", "pythagor"],
                    "sequence": ["直观问题", "动态对象", "数学关系", "应用与边界"], "extensions": ["formula", "coordinate_system", "mathematical_objects", "transformation", "proof_steps"],
                    "rules": "先用几何对象表达变化，再给出公式。函数自变量、定义域和极限条件必须明确。图形和公式同色对应。证明与数值例子分开，不能把一个例子称为普遍证明。",
                    "palette": ["#0D1424", "#63D8CE", "#F7C96B", "#E9EFF7"]},
    "history": {"name": "历史", "style": "archival_timeline", "keywords": ["历史", "朝代", "秦", "汉朝", "唐朝", "宋朝", "明朝", "清朝", "丝绸之路", "工业革命", "罗马", "战争", "history", "silk road"],
                "sequence": ["时空背景", "关键人物与事件", "因果链", "影响与史料边界"], "extensions": ["historical_period", "locations", "characters", "events", "causal_relationships", "historical_sources"],
                "rules": "标明年份、地理位置和史料出处。时间相邻不等于因果成立。地图为示意时必须标注示意，不把现代国界代入古代。存在争议的原因使用有限表述。",
                "palette": ["#1B2028", "#D8B681", "#A6B8BC", "#F3EEE5"]},
    "physics": {"name": "物理", "style": "experimental_diagram", "keywords": ["物理", "牛顿", "力学", "加速度", "电磁", "光学", "量子", "热力学", "physics", "newton"],
                "sequence": ["可观察现象", "理想模型", "变量关系", "条件与预测"], "extensions": ["units", "assumptions", "forces", "initial_conditions"],
                "rules": "标明单位、参考系和理想化条件。实验示意与真实实验数据分开。受力图使用合力而非混淆单个力；数学公式的适用范围要随讲解出现。",
                "palette": ["#0B1E29", "#7AD7F0", "#F4B860", "#E8F1F5"]},
    "biology": {"name": "生物", "style": "layered_life_process", "keywords": ["生物", "细胞", "光合作用", "基因", "DNA", "蛋白质", "神经", "生态", "biology", "photosynthesis"],
                "sequence": ["尺度与结构", "过程输入", "机制与流向", "功能和边界"], "extensions": ["scale", "structures", "process_steps", "organism"],
                "rules": "标明细胞、组织或个体尺度。结构图必须注明示意和非比例。物质流与能量流使用不同箭头。不能把目标性语言当作机制解释。",
                "palette": ["#10241F", "#8BDBA5", "#F0CC75", "#EFF5ED"]},
    "economics": {"name": "经济学", "style": "analytical_chart", "keywords": ["经济", "供需", "供给", "需求", "通货膨胀", "利率", "市场", "GDP", "economics", "supply", "demand"],
                  "sequence": ["经济问题", "模型假设", "曲线或数据变化", "解释与局限"], "extensions": ["assumptions", "variables", "data_sources", "model_limits"],
                  "rules": "模型曲线与实测数据明确区分。标明坐标轴、单位、其他条件不变的假设。相关不等于因果。示例数字必须标注假设数据，不提供个体投资建议。",
                  "palette": ["#172231", "#85B7EE", "#F4AA79", "#F1F3F7"]},
    "literature": {"name": "文学", "style": "typographic_imagery", "keywords": ["文学", "诗", "小说", "比喻", "意象", "人物关系", "修辞", "鲁迅", "红楼梦", "literature", "metaphor"],
                   "sequence": ["文本观察", "人物或意象联系", "表达效果", "有依据的解读"], "extensions": ["work", "author", "text_evidence", "interpretations"],
                   "rules": "事实、原文与解读分开。未经核对不能编造原文引句。示例句如为原创要标注。人物关系随文本阶段呈现，不把单一解读称作唯一答案。",
                   "palette": ["#292332", "#D6B7D8", "#E7C28E", "#F7EFF4"]},
}


def scene(title, goal, narration, component, parameters=None, extensions=None):
    return {"title": title, "learning_goal": goal, "narration": narration, "visual_concept": goal,
            "components": [{"id": component, "parameters": {"title": title, **(parameters or {})}}],
            "duration": 15, "animation_sequence": [], "camera": {}, "audio": {}, "extensions": extensions or {}}


LESSONS = {
    "mathematics": [
        {"id": "calculus", "title": "微积分的本质", "aliases": ["微积分", "calculus"],
         "learning_objectives": ["用导数描述瞬时变化", "用积分描述连续累积", "理解变化与累积由微积分基本定理联系"],
         "knowledge": ["导数是差商的极限。", "定积分是黎曼和的极限。", "对连续函数 f，F(x)=∫₀ˣ f(t)dt 满足 F'(x)=f(x)。"],
         "sources": [{"title": "OpenStax Calculus Volume 1: The Fundamental Theorem of Calculus", "url": "https://openstax.org/books/calculus-volume-1/pages/5-3-the-fundamental-theorem-of-calculus"}],
         "scenes": [scene("微积分在问什么？", "把变化和累积作为两个核心问题", "微积分研究两个相连的问题：某一刻变化有多快，以及不断变化的量怎样累积。", "general.relationship", {"labels": ["瞬时变化", "导数", "连续累积", "积分"]}),
                    scene("导数：看局部变化", "让割线趋于切线", "在平方函数上，让两点越来越近。割线趋近切线，横坐标一处的斜率趋近二。", "math.derivative_secant", {"function": "x**2", "x_range": [-1, 3], "x0": 1, "dx_start": 1.5, "dx_end": 0.02}),
                    scene("积分：把小块累加", "用小矩形表示连续累积", "再看曲线下的面积。把小矩形逐一相加，并让每块越来越窄，得到积分的直观含义。", "math.integral_riemann", {"function": "x**2", "bounds": [0, 2], "n_start": 4, "n_end": 32}),
                    scene("两种操作怎样联系？", "连接累积量与其瞬时变化", "把零到某一点的面积记作一个新函数。对连续函数，这个累积函数的导数等于原函数。", "math.formula", {"latex": r"F(x)=\int_0^x f(t)\,\mathrm{d}t\qquad F'(x)=f(x)", "labels": ["条件：f 连续", "微积分基本定理"]}),
                    scene("一个具体例子", "用平方函数检查变化与累积", "平方函数累积成三分之立方；再求导，又回到平方。变化和累积，因此被同一个定理联系起来。", "math.formula", {"latex": r"\int_0^x t^2\,\mathrm{d}t=\frac{x^3}{3}\qquad \frac{\mathrm{d}}{\mathrm{d}x}\left(\frac{x^3}{3}\right)=x^2", "labels": ["积分：累积", "导数：变化"]}, {"formula": "diff(x**3/3,x)=x**2", "proof_steps": ["F(x)=Integral(t**2,(t,0,x))=x**3/3", "diff(F(x),x)=x**2"]})]},
        {"id": "derivative", "title": "导数的几何意义", "aliases": ["导数", "derivative"],
         "learning_objectives": ["区分平均变化率与瞬时变化率", "理解割线趋近切线", "求出 x² 在 x=1 处的导数"],
         "knowledge": ["函数 f(x)=x² 的平均变化率为 ((1+h)²-1)/h=2+h，h≠0。", "当 h 趋近 0 时，割线斜率趋近 2。", "导数表达瞬时变化率；可导性需要极限存在。"],
         "sources": [{"title": "OpenStax Calculus Volume 1: Derivatives", "url": "https://openstax.org/books/calculus-volume-1/pages/3-1-defining-the-derivative"}],
         "scenes": [scene("变化有多快？", "观察曲线与两个点", "沿着平方函数移动，同样向右一步，高度的变化并不一样。怎样描述某一点的变化速度？", "math.derivative_secant", {"function": "x**2", "x_range": [-1, 3], "x0": 1, "dx_start": 1.5, "dx_end": 1.5, "labels": ["f(x)=x²", "平均变化率"]}),
                    scene("两点之间：平均变化率", "用割线斜率表示差商", "连接两个点得到割线。竖直变化除以水平变化，就是这段区间的平均变化率。", "math.derivative_secant", {"function": "x**2", "x_range": [-1, 3], "x0": 1, "dx_start": 1.5, "dx_end": 0.8, "latex": r"\frac{\Delta y}{\Delta x}=2+h"}),
                    scene("让两点逐渐靠近", "让割线趋于切线", "把第二个点向第一个点靠近。水平距离趋近零，割线逐渐接近切线，斜率趋近二。", "math.derivative_secant", {"function": "x**2", "x_range": [-1, 3], "x0": 1, "dx_start": 0.8, "dx_end": 0.02}),
                    scene("导数：瞬时变化率", "连接数值极限与导数定义", "在横坐标一处，平方函数的导数是二。导数就是差商的极限，前提是这个极限存在。", "math.formula", {"latex": r"f'(1)=\lim_{h\to 0}(2+h)=2", "labels": ["平均变化率", "取极限", "瞬时变化率"]}, {"formula": "f'(1)=2", "proof_steps": ["((1+h)^2-1)/h=2+h, h≠0", "lim(h→0)(2+h)=2"]})]},
        {"id": "integral", "title": "积分与面积", "aliases": ["积分", "integral"],
         "learning_objectives": ["理解用小矩形逼近面积", "区分有限求和与积分", "计算 x² 在 [0,2] 上的定积分"],
         "knowledge": ["在 [0,2] 上以等宽矩形近似 x² 下方的面积。", "连续函数的黎曼和在网格趋于零时收敛到定积分。", "∫₀² x²dx = [x³/3]₀² = 8/3。"],
         "sources": [{"title": "OpenStax Calculus Volume 1: The Definite Integral", "url": "https://openstax.org/books/calculus-volume-1/pages/5-2-the-definite-integral"}],
         "scenes": [scene("曲线下的面积", "提出不规则面积问题", "我们想求平方函数从零到二之间的曲线下面积。边界是弯的，普通长方形公式不能直接使用。", "math.integral_riemann", {"function": "x**2", "bounds": [0, 2], "n_start": 4, "n_end": 4}),
                    scene("把面积分成小块", "构造中点矩形近似", "先把区间切成四份，用每段中点的函数值作高度。小矩形面积相加，得到一个近似值。", "math.integral_riemann", {"function": "x**2", "bounds": [0, 2], "n_start": 4, "n_end": 8, "labels": ["宽 Δx", "高 f(x)"]}),
                    scene("分得越细，误差越小", "展示黎曼和收敛", "不断增加矩形数量，每块变得更窄。对这个连续函数，矩形面积的总和会趋向确定的极限。", "math.integral_riemann", {"function": "x**2", "bounds": [0, 2], "n_start": 8, "n_end": 32}),
                    scene("极限就是定积分", "用原函数求出面积", "这个极限就是定积分。平方函数的原函数是三分之立方，代入上下限，面积等于三分之八。", "math.formula", {"latex": r"\int_0^2 x^2\,\mathrm{d}x=\left[\frac{x^3}{3}\right]_0^2=\frac{8}{3}", "labels": ["分割", "求和", "取极限"]}, {"formula": "Integral(x**2,(x,0,2))=8/3", "coordinate_system": {"x": [0, 2]}})]},
        {"id": "pythagorean", "title": "勾股定理", "aliases": ["勾股", "pythagor"],
         "learning_objectives": ["识别直角三角形的斜边", "用面积理解 a²+b²=c²", "区别数值验证与一般证明"],
         "knowledge": ["直角三角形中，直角所对的边是斜边。", "对直角三角形，a²+b²=c²。", "3²+4²=5² 是示例而不是一般证明。"],
         "sources": [{"title": "OpenStax Prealgebra: Use the Pythagorean Theorem", "url": "https://openstax.org/books/prealgebra-2e/pages/9-5-use-properties-of-angles-triangles-and-the-pythagorean-theorem"}],
         "scenes": [scene("三条边，一个直角", "辨认斜边", "先找直角。与直角相对的边叫斜边，也是直角三角形中最长的一条边。", "math.pythagorean", {"a": 3, "b": 4, "c": 5, "labels": ["直角边 a", "直角边 b", "斜边 c"]}),
                    scene("在每条边上搭正方形", "把边长平方转换为面积", "分别以三条边为边长搭正方形。它们的面积，就是三条边长各自的平方。", "math.pythagorean", {"a": 3, "b": 4, "c": 5, "labels": ["a²=9", "b²=16", "c²=25"]}),
                    scene("面积之间的关系", "观察面积等式", "勾股定理说，两个直角边上正方形的面积之和，等于斜边上正方形的面积。", "math.pythagorean", {"a": 3, "b": 4, "c": 5, "latex": r"a^2+b^2=c^2"}),
                    scene("数值验证与适用条件", "避免把示例当作一般证明", "三、四、五满足九加十六等于二十五。这验证了一个例子；一般证明还需要拼图或相似三角形。", "math.formula", {"latex": r"3^2+4^2=5^2\qquad a^2+b^2=c^2", "labels": ["条件：直角三角形", "示例验证 ≠ 一般证明"]}, {"proof_steps": [], "limitations": "此示范课解释定理并做数值验证，不声称给出一般证明。"})]},
    ],
    "history": [{"id": "silk_road", "title": "丝绸之路", "aliases": ["丝绸之路", "silk road"],
                 "learning_objectives": ["理解丝绸之路是交流网络", "认识张骞出使的历史背景", "区分交流过程与单一线性因果"],
                 "knowledge": ["丝绸之路是跨欧亚大陆、多时期演变的交流网络。", "张骞在公元前二世纪出使西域。", "商品、技术、宗教和知识沿多条路线传播。"],
                 "sources": [{"title": "UNESCO: About the Silk Roads", "url": "https://en.unesco.org/silkroad/about-silk-roads"}],
                 "scenes": [scene("一条路，还是一张网？", "把单一路线改为网络概念", "丝绸之路并不是一条固定的道路，而是不同时期不断变化的交通与交流网络。", "general.relationship", {"labels": ["东亚", "中亚", "西亚", "地中海"], "title": "交流网络示意，非地理地图"}),
                            scene("汉代的西域往来", "把事件放在时间背景中", "公元前二世纪，张骞出使西域。汉朝对西域的了解与往来，成为这一时期交流的重要背景。", "general.timeline", {"labels": ["公元前二世纪", "张骞出使", "往来加深"]}),
                            scene("流动的不只有丝绸", "扩展交换内容", "商旅携带商品，也促进技术、信仰和知识传播。交流往往经过多个中间地区，逐步发生。", "general.process", {"labels": ["商品交换", "人员往来", "技术与文化传播"]}),
                            scene("从网络理解历史", "保留史料与因果边界", "理解丝绸之路，要同时观察路线、人物和时代。图中连线只是关系示意，不能代替真实的历史地图。", "general.relationship", {"labels": ["时代", "地区", "人群", "史料"]}, {"historical_period": "汉代及后续时期", "locations": ["东亚", "中亚", "西亚"], "historical_sources": ["UNESCO Silk Roads"]})]}],
    "physics": [{"id": "newton", "title": "牛顿第二定律", "aliases": ["牛顿第二定律", "newton's second law", "newton second law"],
                 "learning_objectives": ["识别合力与加速度的关系", "理解质量对加速度的影响", "知道经典模型的适用条件"],
                 "knowledge": ["在惯性系、质量不变的经典力学条件下，F_net=ma。", "质量不变时，加速度与合力成正比。", "合力一定时，加速度与质量成反比。"],
                 "sources": [{"title": "OpenStax University Physics: Newton's Second Law", "url": "https://openstax.org/books/university-physics-volume-1/pages/5-3-newtons-second-law"}],
                 "scenes": [scene("力改变运动状态", "从速度变化引出加速度", "推小车时，我们关心的是速度怎样变化。描述速度变化快慢的物理量，叫作加速度。", "general.process", {"labels": ["合力", "速度变化", "加速度"]}),
                            scene("合力越大，加速度越大", "固定质量比较合力", "固定质量为一千克。合力从一牛顿增加到三牛顿，加速度也从一增加到三米每二次方秒。", "general.chart", {"labels": ["1 N", "2 N", "3 N"], "values": [1, 2, 3], "title": "假设 m=1 kg，a 单位 m/s²"}),
                            scene("质量也决定变化", "固定合力比较质量", "同样的合力作用下，质量越大，加速度越小。因此不能只比较推力，而忽略物体质量。", "math.formula", {"latex": r"a=\frac{F_{\mathrm{net}}}{m}", "labels": ["合力 F_net：N", "质量 m：kg", "加速度 a：m/s²"]}),
                            scene("写出模型，也说明条件", "总结适用范围", "牛顿第二定律写作合力等于质量乘加速度。这里采用惯性参考系，质量不变，并处于经典力学范围。", "math.formula", {"latex": r"F_{\mathrm{net}}=ma", "labels": ["惯性系", "质量不变", "经典力学"]}, {"units": {"force": "N", "mass": "kg", "acceleration": "m/s²"}, "assumptions": ["惯性系", "恒定质量", "经典非相对论范围"]})]}],
    "biology": [{"id": "photosynthesis", "title": "光合作用", "aliases": ["光合作用", "photosynthesis"],
                 "learning_objectives": ["区分光合作用的物质与能量来源", "了解叶绿体内两类过程", "认识总反应式是简化表达"],
                 "knowledge": ["植物光合作用把光能转为化学能。", "光反应发生在类囊体膜，释放的氧气来自水。", "碳固定利用二氧化碳合成有机物，葡萄糖总反应式是简化概括。"],
                 "sources": [{"title": "OpenStax Biology 2e: Overview of Photosynthesis", "url": "https://openstax.org/books/biology-2e/pages/8-1-overview-of-photosynthesis"}],
                 "scenes": [scene("植物怎样储存太阳能？", "区分物质和能量输入", "植物吸收光，同时取得水和二氧化碳。光提供能量，水和二氧化碳提供反应所需的物质。", "general.process", {"labels": ["光能", "水 + 二氧化碳", "有机物 + 氧气"]}),
                            scene("进入叶绿体", "确定细胞器与过程位置", "在叶绿体中，光反应位于类囊体膜。它把光能转化，并由水释放氧气。这里的结构仅作示意。", "general.relationship", {"labels": ["叶绿体", "类囊体膜", "光反应", "氧气"]}),
                            scene("把碳固定下来", "衔接两类反应", "碳固定在叶绿体基质中进行，利用光反应提供的能量载体，将二氧化碳的碳用于合成有机物。", "general.process", {"labels": ["光反应", "能量载体", "碳固定", "有机物"]}),
                            scene("读懂简化总式", "避免混淆简式和一步反应", "总反应式概括了物质变化，却不表示过程一步完成。氧气来自水，复杂的中间反应被简化了。", "math.formula", {"latex": r"6\mathrm{CO}_2+6\mathrm{H}_2\mathrm{O}\xrightarrow{\mathrm{light}}\mathrm{C}_6\mathrm{H}_{12}\mathrm{O}_6+6\mathrm{O}_2", "labels": ["总式为简化表达", "氧气来自水"]}, {"scale": "细胞器", "structures": ["叶绿体", "类囊体膜", "基质"], "organism": "绿色植物"})]}],
    "economics": [{"id": "supply_demand", "title": "供需关系", "aliases": ["供需", "供给", "需求", "supply", "demand"],
                 "learning_objectives": ["理解需求量与需求的区别", "认识供需均衡模型", "知道图中数字是教学假设"],
                 "knowledge": ["在其他条件不变时，简单需求模型中价格越高需求量越低。", "简单供给模型中价格越高供给量越高。", "需求曲线整体移动与沿曲线移动不同，模型数据并非现实预测。"],
                 "sources": [{"title": "OpenStax Principles of Economics: Demand, Supply, and Equilibrium", "url": "https://openstax.org/books/principles-economics-3e/pages/3-1-demand-supply-and-equilibrium-in-markets-for-goods-and-services"}],
                 "scenes": [scene("从一个简化市场开始", "明确模型条件", "想象一个简化市场，先假设收入、偏好和生产条件不变。接下来的数字都是教学假设。", "general.process", {"labels": ["买方需求", "市场价格", "卖方供给"]}),
                            scene("价格与需求量", "观察沿需求曲线变化", "价格从一元涨到三元，假设需求量从九份降到三份。这是在同一条需求关系上移动。", "general.chart", {"labels": ["价格 1 元", "价格 2 元", "价格 3 元"], "values": [9, 6, 3], "title": "假设需求量（份），非实测数据"}),
                            scene("价格与供给量", "观察供给关系", "同样三档价格下，假设供给量从三份增到九份。在两元时，供给和需求都为六份。", "general.chart", {"labels": ["价格 1 元", "价格 2 元", "价格 3 元"], "values": [3, 6, 9], "title": "假设供给量（份），均衡价 2 元"}),
                            scene("模型有条件", "区分需求变化与需求量变化", "如果收入或偏好改变，需求关系本身可能移动。简单模型帮助解释方向，不保证预测真实市场。", "general.relationship", {"labels": ["收入", "偏好", "需求关系", "价格与数量"]}, {"assumptions": ["其他条件不变", "教学假设数据"], "model_limits": ["非现实市场预测"]})]}],
    "literature": [{"id": "metaphor", "title": "比喻的表达", "aliases": ["比喻", "修辞", "metaphor"],
                 "learning_objectives": ["识别本体与喻体", "寻找二者共同特征", "结合语境评价表达效果"],
                 "knowledge": ["比喻通过相似性连接本体与喻体。", "分析比喻需要说明相似点及其表达作用。", "同一比喻可以有多个受语境约束的解读。"],
                 "sources": [{"title": "Poetry Foundation: Metaphor", "url": "https://www.poetryfoundation.org/education/glossary/metaphor"}],
                 "scenes": [scene("把抽象感受变成画面", "用原创句子观察比喻", "看这个原创示例：记忆像一座灯塔。记忆是本体，灯塔是用来帮助我们理解它的喻体。", "general.relationship", {"labels": ["记忆：本体", "像", "灯塔：喻体"], "title": "原创示例：记忆像一座灯塔"}),
                            scene("相似点在哪里？", "寻找意象之间的联系", "灯塔能够指引方向。把记忆比作灯塔，可以让人想到过去的经验对今天的选择产生影响。", "general.process", {"labels": ["灯塔", "指引", "记忆", "选择"]}),
                            scene("从解释到表达效果", "说清具体表达作用", "比喻把难以看见的记忆，变成一个可以想象的形象。分析时，应说明具体联系，而不只说生动形象。", "general.relationship", {"labels": ["抽象的记忆", "可见的灯塔", "指引的感受"]}),
                            scene("让解读回到语境", "明确解释边界", "如果上下文写的是孤独，灯塔也可能带来另一种感受。解读要回到语境，并说明证据支持什么。", "general.process", {"labels": ["文本语境", "相似点", "表达效果", "证据"]}, {"work": "原创教学示例", "text_evidence": ["记忆像一座灯塔"], "interpretations": ["记忆具有指引作用；最终解释取决于上下文"]})]}],
}


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build():
    for name, pack in PACKS.items():
        folder = ROOT / "domains" / name
        lessons = LESSONS[name]
        for lesson in lessons:
            lesson["teaching_structure"] = pack["sequence"]
            for index, item in enumerate(lesson["scenes"]):
                item["scene_id"] = f"scene_{index + 1:02d}"
                item["domain"] = name
                item["renderer"] = "manim" if name in ("mathematics", "physics") else "canvas"
            write_json(folder / "examples" / f"{lesson['id']}.json", lesson)
        write_json(folder / "pack.json", {"id": name, "name": pack["name"], "version": "1.0", "style": pack["style"],
                                          "keywords": pack["keywords"], "extensions": pack["extensions"],
                                          "lessons": [{"title": lesson["title"], "aliases": lesson["aliases"], "file": f"{lesson['id']}.json"} for lesson in lessons]})
        (folder / "plan.md").write_text(f"# {pack['name']}教学规划\n\n" + pack["rules"] + "\n\n教学顺序：" + " → ".join(pack["sequence"]) +
                                       "\n\n专业扩展：" + "、".join(pack["extensions"]) + "\n\n每个场景只推进一个核心关系，先写教学目标和旁白，再写对象起止状态与动画。"
                                       "默认使用共享时长和画幅，不追问用户。演示模式仅覆盖 examples 中人工编写的课程；live 模式必须记录可追溯的资料。"
                                       "不增加 AI 审片、质量评分或反复修订环节。技术检查仅验证 Schema、依赖、进程和产物。\n", encoding="utf-8")
        colors = pack["palette"]
        write_json(folder / "styles" / "default.json", {"id": pack["style"], "background": colors[0], "primary": colors[1], "accent": colors[2], "text": colors[3],
                                                         "font": "SimSun", "english_font": "Times New Roman", "subtitle_font": "Microsoft YaHei", "subtitle_weight": "BOLD", "subtitle_outline": "#161044", "fallback_fonts": ["Noto Serif CJK SC", "Liberation Serif"],
                                                         "safe_margin": 0.08, "attention_opacity": {"focus": 1.0, "context": 0.4, "grid": 0.15},
                                                         "motion": {"reveal_seconds": 1.5, "hold_after_key_seconds": 2.0, "easing": "smoothstep"},
                                                         "principles": ["每个动作揭示一个关系", "一致的语义配色", "关键结论保留阅读时间", "画面与旁白共用场景时间轴"]})
        component_ids = sorted({component["id"] for lesson in lessons for item in lesson["scenes"] for component in item["components"]})
        write_json(folder / "components" / "registry.json", {"component_ids": component_ids, "implementation": "renderers/", "policy": "复用受控模板；模型只提供数据，不直接执行模型返回的 Python。"})
        write_json(folder / "audio" / "profile.json", {"narration": "minimax", "voice_name": "温润青年", "bgm_gain": 0.12, "voice_priority": True,
                                                       "bgm_source": "BGM_PATH 环境变量", "effects": [], "note": "未内置第三方音乐或音效；无 BGM 时保留旁白。"})
        write_json(folder / "renderers" / "default.json", {"preferred": "manim" if name in ("mathematics", "physics") else "canvas",
                                                           "adapters": ["manim", "canvas"], "future_adapters": ["remotion", "blender"],
                                                           "fps": 30, "resolution": [1280, 720]})
        (folder / "examples" / "README.md").write_text("# 示例课程\n\n这里保存人工编写的教学数据与可复现组件参数，JSON 是示例源码。"
                                                       "运行 CLI 后生成独立场景源码与成品 MP4；仓库不把尚未渲染的示例称为成品视频。\n", encoding="utf-8")
    animation_assets = []
    for component in ("math.derivative_secant", "math.integral_riemann", "math.pythagorean", "math.formula", "general.title", "general.timeline", "general.relationship", "general.process", "general.chart"):
        animation_assets.append({"id": component, "component_id": component, "kind": "animation", "level": "complete",
                                 "domains": ["general"] if component.startswith("general.") or component == "math.formula" else ["mathematics", "physics"],
                                 "scenes": [component.split(".")[1]], "animations": ["reveal", "transform"], "renderer": ["manim", "canvas"],
                                 "source": "renderers/", "license": "project-original", "version": "1.0"})
    animation_assets += [{"id": "primitive.axes", "kind": "animation", "level": "basic", "domains": ["general"], "supports": ["general.composed_chart"],
                          "scenes": ["chart"], "animations": ["draw"], "source": "renderers/", "license": "project-original"},
                         {"id": "primitive.labels", "kind": "animation", "level": "basic", "domains": ["general"], "supports": ["general.composed_chart"],
                          "scenes": ["chart", "timeline"], "animations": ["reveal"], "source": "renderers/", "license": "project-original"},
                         {"id": "primitive.generic", "kind": "animation", "level": "primitive", "domains": ["general"], "supports": [],
                          "scenes": ["custom"], "animations": ["reveal"], "source": "renderers/", "license": "project-original"}]
    assets = animation_assets + [{"id": f"style.{name}", "kind": "design", "domains": [name], "source": f"domains/{name}/styles/default.json", "license": "project-original"} for name in PACKS]
    assets += [{"id": "reference.manim_video", "kind": "reference", "domains": ["mathematics", "physics"], "source": "https://github.com/browser-use/video-use/tree/main/skills/manim-video", "downloaded": False, "rights": "External reference only; no source copied."},
               {"id": "reference.motion_showreel", "kind": "reference", "domains": ["general"], "source": "https://github.com/ConardLi/garden-skills/tree/main/skills/motion-showreel", "downloaded": False, "rights": "External reference only; no media copied."},
               {"id": "audio.user_bgm", "kind": "audio", "domains": ["general"], "source": "env:BGM_PATH", "available": (ROOT / "assets/audio/vibe-bgm.m4a").is_file(), "local_path": "assets/audio/vibe-bgm.m4a", "rights": "User-supplied; resolve at runtime."}]
    write_json(ROOT / "assets" / "catalog.json", {"version": "1.0", "assets": assets})
    # Phase 2 history metadata supersedes the intentionally retained legacy demo.
    from domains.history.definition import install_metadata
    install_metadata(ROOT)
    for subdir in ("audio", "fonts", "textures", "reference_videos"):
        path = ROOT / "assets" / subdir
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").touch()
    (ROOT / "assets" / "README.md").write_text("# 素材目录\n\n`catalog.json` 记录设计规范、动画组件、外部参考和用户音频占位。"
                                             "按学科、场景、动画类型检索；完整组件优先，其次组合基础组件，最后选择通用绘图路径。"
                                             "素材匹配记录与执行能力不同：渲染器会拒绝尚未实现的组件，不能把检索成功当作已经实现动画。\n\n"
                                             "没有下载第三方视频、字体或 BGM。用户提供的 Linux BGM 路径须通过本机 BGM_PATH 配置；"
                                             "运行时应记录实际可用性。外部参考用于借鉴叙事结构和工作流，不复制原视频画面或源码。\n", encoding="utf-8")


if __name__ == "__main__":
    build()
