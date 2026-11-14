"""Domain routing and teaching/visual plans; no interactive clarification stage."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from harness.schemas import Domain, Scene, TeachingPlan, VideoRequest, VisualPlan

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
            "renderer: 数学和物理用 manim，其他用 canvas。可用组件仅 math.derivative_secant、"
            "math.integral_riemann、math.pythagorean、math.formula、general.title、general.timeline、"
            "general.relationship、general.process、general.chart。数学图像 function 仅 x**2、sin(x)、cos(x)、x、exp(x)。"
            "derivative 参数 x0,dx_start,dx_end,x_range；integral 参数 bounds,n_start,n_end；"
            "pythagorean 参数 a,b,c 必须满足勾股定理；math.formula 必须用 parameters.latex 存放真正的 LaTeX 数学表达式，"
            "不包含美元符号或文档环境；分数用 \\frac，极限用 \\lim，积分用 \\int，禁止用 Unicode 上下标或纯文本模拟公式。"
            "latex 字段中仅放数学表达式，中文说明放 labels，旁白 narration 用自然中文，不读出 LaTeX 命令。"
            "其他组件参数 title,labels（字符串列表）,values（数字列表）。给每个场景说明变化的起止状态。\n" + pack_rules
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
        scene.setdefault("renderer", "manim" if scene["domain"] in ("mathematics", "physics", Domain.mathematics, Domain.physics) else "canvas")
        scene["duration"] = max(0.1, float(scene.get("duration", 15)) / total * request.duration)
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
        updated.camera = {"framing": "safe_area", "motion": "static", **scene.camera}
        updated.audio = {"narration_priority": True, "bgm_gain": 0.12, **scene.audio}
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
