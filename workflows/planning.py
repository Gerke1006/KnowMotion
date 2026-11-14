"""Domain routing and teaching/visual plans; no interactive clarification stage."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from harness.schemas import Domain, Scene, TeachingPlan, VideoRequest, VisualPlan
from harness.history import CONTRACTS as HISTORY_COMPONENTS, normalize_history_component, referenced_source_ids

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ROOT / "domains"


def load_pack(domain: Domain | str) -> dict[str, Any]:
    name = domain.value if isinstance(domain, Domain) else str(domain)
    if name not in {item.value for item in Domain}:
        raise ValueError(f"Unknown domain: {name}")
    return json.loads((DOMAINS / name / "pack.json").read_text(encoding="utf-8"))


def route_topic(topic: str, **overrides: Any) -> VideoRequest:
    """Use pack vocabulary with longest-match weighting; callers may override defaults."""
    normalized = topic.strip().casefold()
    if not normalized:
        raise ValueError("知识主题不能为空")
    scores: dict[Domain, int] = {}
    for domain in Domain:
        pack = load_pack(domain)
        scores[domain] = sum(len(word) ** 2 for word in pack["keywords"] if word.casefold() in normalized)
    selected = max(scores, key=scores.get)
    if not scores[selected]:
        selected = Domain.mathematics
    supplied = {k: v for k, v in overrides.items() if v is not None and k in VideoRequest.model_fields}
    selected = Domain(supplied.pop("domain", selected))
    pack = load_pack(selected)
    ratio = supplied.get("aspect_ratio", "16:9")
    width, height = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}.get(ratio, (1280, 720))
    defaults = dict(topic=topic.strip(), title=topic.strip(), domain=selected, audience="高中生与大学初学者", duration=60,
                    aspect_ratio=ratio, width=width, height=height, fps=30, style=pack["style"], mode="demo")
    defaults.update(supplied)
    return VideoRequest(**defaults)


def demo_lesson(request: VideoRequest) -> dict[str, Any]:
    topic = request.topic.casefold()
    pack = load_pack(request.domain)
    for entry in pack["lessons"]:
        if any(alias.casefold() in topic for alias in entry["aliases"]):
            return json.loads((DOMAINS / request.domain.value / "examples" / entry["file"]).read_text(encoding="utf-8"))
    examples = "、".join(item["title"] for item in pack["lessons"])
    raise ValueError(f"演示模式尚无“{request.topic}”的已编写课程。可用主题：{examples}。任意主题请使用 live 模式。")


async def plan(request: VideoRequest, research: dict[str, Any], gateway: Any = None) -> TeachingPlan:
    """Create a teaching sequence first; rendering choices are refined separately."""
    history_sources = [{**{key: value for key, value in source.items() if key != "evidence_text"},
                        "id": source.get("id") or f"source_{index + 1:02d}"}
                       for index, source in enumerate(research.get("sources", []))]
    if request.domain == Domain.history:
        research = {**research, "sources": history_sources}
    if request.mode == "demo":
        content = demo_lesson(request)
    else:
        if gateway is None:
            raise ValueError("live 模式需要配置模型网关")
        pack_rules = (DOMAINS / request.domain.value / "plan.md").read_text(encoding="utf-8")
        system = (
            "你是知识视频教学规划器。只输出 JSON，不追问用户，不审片或循环重写。"
            "只根据给定研究材料写可核对的事实；区分史料、解释、假设，禁止编造来源、日期和数据。"
            "每个场景允许独立 domain，遵守该领域事实约束。返回 learning_objectives、teaching_structure、scenes。"
            "learning_objectives 和 teaching_structure 均必须是字符串数组，不能是包含 sequence 的对象；scenes 是场景对象数组。"
            "每个 scene 包含 scene_id（如 scene_01）、title、domain、learning_goal、narration、visual_concept、"
            "components（id,parameters）、animation_sequence（对象列表）、camera（对象）、audio（对象）、"
            "duration（秒）、renderer、extensions（对象）。写 3 到 6 个场景，总时长为请求 duration，"
            "优先保留核心概念，禁止大段塞满画面；如给定 narration_char_budget，严格遵守全片旁白字数预算。"
            "全片是一段连续讲解：相邻场景用因果、承接或问题自然过渡，避免逐幕重复开场、总结或说‘下一幕’。"
            "场景切换不插入等待或静默，动画跟随实际旁白结束；duration 是常速讲稿预算，导出时统一倍速。"
            "每个场景当前只使用一个主要组件，可在该组件 parameters 中组合标签、公式和图形。"
            "renderer: 数学和物理用 manim，历史用 remotion，其他用 canvas。可用组件仅 math.derivative_secant、"
            "math.integral_riemann、math.pythagorean、math.formula、general.title、general.timeline、"
            "general.relationship、general.process、general.chart、history.map、history.timeline、history.person。数学图像 function 仅 x**2、sin(x)、cos(x)、x、exp(x)。"
            "derivative 参数 x0,dx_start,dx_end,x_range；integral 参数 bounds,n_start,n_end；"
            "pythagorean 参数 a,b,c 必须满足勾股定理；math.formula 必须用 parameters.latex 存放真正的 LaTeX 数学表达式，"
            "不包含美元符号或文档环境；分数用 \\frac，极限用 \\lim，积分用 \\int，禁止用 Unicode 上下标或纯文本模拟公式。"
            "latex 字段中仅放数学表达式，中文说明放 labels，旁白 narration 用自然中文，不读出 LaTeX 命令。"
            "其他组件参数 title,labels（字符串列表）,values（数字列表）。给每个场景说明变化的起止状态。\n" + pack_rules
        )
        if request.domain == Domain.history:
            system += (
                "\n历史组件只用 history.map、history.timeline、history.person。"
                "只有 research.geography.records 至少有2个与主题相关的有据地点时才使用地图，短片覆盖三种组件；"
                "无可靠坐标目录时只用时间线与人物组件，不编造经纬度，不借用不相关主题的地点。"
                "每幕只能有一个 component，renderer 固定 remotion。所有 parameters.source_ids 必须为"
                "输入 research.sources 中 id 组成的非空字符串数组，不能填写标题或链接。"
                "history.map 参数：title(字符串，可选)，locations(2到8个对象，每个必须有 id/name 字符串及 lon/lat 数字)，"
                "routes(数组，每项 from/to 是已有 location.id，label 字符串，kind 固定 schematic)，"
                "viewport(可选，west/east/south/north 数字，包含全部地点)，note(字符串)，source_ids(字符串数组)。"
                "有 research.geography 时，地点名称、id、经纬度须从提供的地名目录选择，不能臆造坐标。"
                "地图常驻说明现代近似定位、路线为示意；不绘制未经史料支持的疆域。"
                "路线label描述连接的两处地点或交流关系；方位词必须符合该段实际经纬度，不用整条网络的方向替代局部方向。"
                "history.timeline 参数：title(可选字符串)，events(2到7个对象，year 数字，label/detail 字符串，"
                "source_ids 可选字符串数组)，range(可选两个递增数字)，note(字符串)，source_ids(字符串数组)。"
                "公元前年用负数，无0年；事件必须有资料支持，争议纪年不要伪装成唯一精确年份。"
                "events 可加 date_label 字符串；世纪、约数、范围或不确定日期必须填写 date_label，"
                "例如‘约公元前2世纪’或‘公元前139/138年（记载有异）’，year 此时仅供时间轴定位，不是精确史实。"
                "history.person 参数：name/role/years 均为字符串（years 不是数组），facts 是1到4个短字符串，"
                "related 可选数组，每项仅 name/relation 字符串，source_ids 字符串数组。"
                "未提供经过许可的画像时不要填写 portrait_asset，用姓名符号；资料不明的生卒年用活动时期。"
                "只有 research.portraits 明确提供的 portrait.path 才可写入 portrait_asset，必须逐字使用该 path，不能编造文件名。"
                "例如目录若提供 portraits/zhang-qian-mogao.jpg，可作为后世绘画使用，不能称为生前真容；"
                "画面的许可和后世作品说明由渲染器使用该素材元数据 caption 标注，不得否认或改写这种限定。"
                "标题最多20字，地点及事件label最多12字，事件detail和人物facts每项最多40字。"
                "所有可见文案（标题、note、label、detail、facts）面向普通观众，不得出现 date_label、source_ids、"
                "viewport、portrait_asset 等字段名、JSON 或组件实现说明。"
                "明确区分人物贡献、时代条件与长期交流网络，不把时间先后写成必然因果。"
            )
        constraints = {}
        if request.narration_char_budget:
            budget = request.narration_char_budget
            minimum = round(budget * .9)
            system += (f"\n本次制作短版，最重要的长度限制：全片所有 narration 合计 {minimum} 到 {budget} 个字符（含标点），"
                       "不是每幕的字数。只写 4 幕，每幕约占总预算四分之一，每幕仅一个主要组件。"
                       "精简讲解，避免重复开场、总结及额外比喻；绝不能输出长篇讲稿。")
            constraints = {"total_narration_characters": {"min": minimum, "max": budget}, "scene_count": 4,
                           "characters_include_punctuation": True}
        content = await gateway.generate_json(system, json.dumps({"request": request.model_dump(mode="json"),
            "research": research, "narration_constraints": constraints}, ensure_ascii=False))
    raw_scenes = content.get("scenes", [])
    if not 1 <= len(raw_scenes) <= 12:
        raise ValueError("教学计划需要 1 到 12 个场景")
    # Planned durations are budgets; rendering fits each scene to measured narration.
    total = sum(float(scene.get("duration", 15)) for scene in raw_scenes)
    if total <= 0:
        raise ValueError("场景总时长必须为正")
    scenes = []
    for index, raw in enumerate(raw_scenes):
        scene = dict(raw)
        scene.setdefault("scene_id", f"scene_{index + 1:02d}")
        scene.setdefault("domain", request.domain)
        scene.setdefault("renderer", "manim" if scene["domain"] in ("mathematics", "physics", Domain.mathematics, Domain.physics)
                         else "remotion" if scene["domain"] in ("history", Domain.history) and request.mode == "live" else "canvas")
        components = scene.get("components", [])
        is_history = scene["domain"] in ("history", Domain.history)
        if is_history and request.mode == "live":
            if len(components) != 1 or components[0].get("id") not in HISTORY_COMPONENTS:
                raise ValueError("历史 live 场景必须使用一个 history.map、history.timeline 或 history.person 组件")
        if any(component.get("id") in HISTORY_COMPONENTS for component in components):
            scene["components"] = [normalize_history_component(component, sources=history_sources,
                                    require_sources=request.mode == "live")
                                    if component.get("id") in HISTORY_COMPONENTS else component for component in components]
            if request.mode == "live":
                anchors = {point["id"]: point for point in research.get("geography", {}).get("records", [])}
                for component in scene["components"]:
                    if component.get("id") != "history.map":
                        continue
                    for point in component["parameters"]["locations"]:
                        anchor = anchors.get(point["id"])
                        if not anchor or any(not math.isclose(point[axis], anchor[axis], rel_tol=0, abs_tol=1e-5)
                                             for axis in ("lon", "lat")):
                            raise ValueError("历史地图地点必须使用本次研究中可追溯的坐标；无可靠坐标请使用时间线或人物组件")
            scene["renderer"] = "remotion"
            cited = referenced_source_ids(scene["components"])
            extensions = dict(scene.get("extensions", {}))
            extensions["historical_sources"] = [{key: source[key] for key in ("id", "title", "url") if key in source}
                                                 for source in history_sources if source["id"] in cited]
            scene["extensions"] = extensions
        scene["duration"] = max(0.1, float(scene.get("duration", 15)) / total * request.duration)
        if (request.mode == "live" and request.domain == Domain.mathematics
                and scene["domain"] in ("mathematics", Domain.mathematics)):
            from harness.math_animation import validate_math_scene
            if scene.get("extensions", {}).get("math_animation_version") != "1.0":
                raise ValueError("New live mathematical scenes require math_animation_version=1.0")
            validate_math_scene(scene)
        scenes.append(Scene.model_validate(scene))
    if len({scene.scene_id for scene in scenes}) != len(scenes):
        raise ValueError("场景 ID 必须唯一")
    structure = content["teaching_structure"]
    if isinstance(structure, dict) and isinstance(structure.get("sequence"), list):
        structure = structure["sequence"]
    return TeachingPlan(request=request, learning_objectives=content["learning_objectives"],
                        teaching_structure=structure, scenes=scenes,
                        sources=research.get("sources", []))


def visual_plan(teaching: TeachingPlan) -> VisualPlan:
    """Map each scene through its own domain pack; keep pedagogy immutable."""
    scenes = []
    for scene in teaching.scenes:
        pack = load_pack(scene.domain)
        updated = scene.model_copy(deep=True)
        if any(component.id in HISTORY_COMPONENTS for component in updated.components):
            updated.renderer = "remotion"
        updated.camera = {"framing": "safe_area", "motion": "static", **scene.camera}
        updated.audio = {"narration_priority": True, "bgm_gain": .30 if scene.domain == Domain.history else .12, **scene.audio}
        scene_style = json.loads((DOMAINS / scene.domain.value / "styles" / "default.json").read_text(encoding="utf-8"))
        updated.extensions = {**scene.extensions, "pack": pack["id"], "style": pack["style"], "visual_style": scene_style}
        # x_range is the camera viewport. Fit a valid moving secant point into
        # view without changing the Agent's function, anchor or motion interval.
        for component in updated.components:
            if component.id != "math.derivative_secant":
                continue
            params = component.parameters
            try:
                xmin, xmax = map(float, params.get("x_range", [-1, 3]))
                x0 = float(params.get("x0", 1))
                start, end = float(params.get("dx_start", 1.5)), float(params.get("dx_end", .02))
            except (TypeError, ValueError):
                continue  # The renderer reports invalid mathematical parameters.
            if (all(math.isfinite(v) for v in (xmin, xmax, x0, start, end))
                    and xmin <= x0 < xmax and 0 < end <= start and x0 + start > xmax):
                params["x_range"] = [xmin, x0 + start + .05 * (xmax - xmin)]
                updated.extensions["viewport_adjustment"] = {"original": [xmin, xmax], "fitted": params["x_range"]}
        if not updated.animation_sequence:
            updated.animation_sequence = [
                {"action": "reveal", "at": 0, "duration": min(1.5, scene.duration / 5)},
                {"action": "transform", "at": scene.duration * 0.2, "duration": scene.duration * 0.5},
                {"action": "hold", "at": scene.duration * 0.7, "duration": scene.duration * 0.3},
            ]
        scenes.append(updated)
    style_file = DOMAINS / teaching.request.domain.value / "styles" / "default.json"
    return VisualPlan(scenes=scenes, style=json.loads(style_file.read_text(encoding="utf-8")))
