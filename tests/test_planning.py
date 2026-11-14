import json

import httpx
import pytest
import sympy

from harness.asset_retriever import AssetRetriever
from harness.schemas import ComponentRef, Domain, Scene, TeachingPlan, VisualPlan
from workflows.planning import demo_lesson, plan, route_topic, visual_plan
from workflows.research import _wiki_sources, research
from workflows.storyboard import build_storyboard


@pytest.mark.parametrize("topic,domain", [
    ("微积分的本质", Domain.mathematics), ("丝绸之路", Domain.history), ("牛顿第二定律", Domain.physics),
    ("光合作用", Domain.biology), ("供需关系", Domain.economics), ("比喻的表达", Domain.literature),
    ("DNA复制", Domain.biology), ("Supply and demand", Domain.economics),
])
def test_domain_routing(topic, domain):
    assert route_topic(topic).domain == domain


def test_route_overrides_and_portrait():
    request = route_topic("文学中的数学", domain="literature", aspect_ratio="9:16", unused=True)
    assert request.domain == Domain.literature
    assert (request.width, request.height) == (720, 1280)
    assert request.title == request.topic
    with pytest.raises(ValueError):
        route_topic("  ")


@pytest.mark.parametrize("topic", ["微积分的本质", "导数", "积分", "勾股定理", "丝绸之路", "牛顿第二定律", "光合作用", "供需关系", "比喻"])
async def test_demo_pipeline_without_model(topic):
    request = route_topic(topic, mode="demo", duration=40)
    findings = await research(request)
    teaching = await plan(request, findings)
    visual = visual_plan(teaching)
    manifest = AssetRetriever().retrieve(visual)
    video = build_storyboard(teaching, visual, manifest)
    assert sum(scene.duration for scene in video.scenes) == pytest.approx(40)
    assert video.domain == request.domain
    assert all(asset.tier == "complete" for asset in manifest.assets)
    assert all(source["status"] == "reference_not_fetched" for source in video.sources)
    assert all(scene.narration and scene.animation_sequence for scene in video.scenes)
    assert teaching.scenes[0].extensions.get("pack") is None  # visual stage does not mutate pedagogy


def test_unknown_demo_topic_is_not_fabricated():
    with pytest.raises(ValueError, match="live"):
        demo_lesson(route_topic("黎曼猜想完整证明", mode="demo"))
    with pytest.raises(ValueError, match="live"):
        demo_lesson(route_topic("牛顿第三定律", mode="demo"))


def test_curated_mathematical_claims():
    x, h = sympy.symbols("x h")
    derivative = demo_lesson(route_topic("导数"))
    for raw in derivative["scenes"]:
        component = raw["components"][0]
        if component["id"] == "math.derivative_secant":
            p = component["parameters"]
            expression = sympy.sympify(p["function"])
            quotient = (expression.subs(x, p["x0"]+h)-expression.subs(x, p["x0"]))/h
            assert sympy.limit(quotient, h, 0) == 2
            assert p["dx_start"] >= p["dx_end"] > 0
    assert r"\lim_{h\to 0}" in derivative["scenes"][-1]["components"][0]["parameters"]["latex"]
    assert derivative["scenes"][-1]["components"][0]["parameters"]["latex"].endswith("=2")
    integral = demo_lesson(route_topic("积分"))
    p = integral["scenes"][0]["components"][0]["parameters"]
    actual = sympy.integrate(sympy.sympify(p["function"]), (x, *p["bounds"]))
    assert rf"\frac{{{actual.p}}}{{{actual.q}}}" in integral["scenes"][-1]["components"][0]["parameters"]["latex"]
    for raw in demo_lesson(route_topic("勾股定理"))["scenes"]:
        component = raw["components"][0]
        if component["id"] == "math.pythagorean":
            p = component["parameters"]
            assert p["a"] ** 2 + p["b"] ** 2 == p["c"] ** 2


def test_calculus_example_combines_derivative_and_integral():
    lesson = demo_lesson(route_topic("微积分的本质"))
    components = {component["id"] for scene in lesson["scenes"] for component in scene["components"]}
    assert {"math.derivative_secant", "math.integral_riemann"} <= components
    assert "微积分基本定理" in lesson["scenes"][3]["components"][0]["parameters"]["labels"]


def sample_scene(component_id, domain=Domain.mathematics, scene_id="s1"):
    return Scene(scene_id=scene_id, domain=domain, title="test", learning_goal="test", narration="test",
                 visual_concept="test", components=[ComponentRef(id=component_id)], duration=10)


def test_asset_retrieval_three_levels():
    visual = VisualPlan(scenes=[sample_scene("math.derivative_secant"),
                               sample_scene("general.composed_chart", scene_id="s2"),
                               sample_scene("custom.anything", scene_id="s3")])
    assets = AssetRetriever().retrieve(visual).assets
    assert [asset.tier for asset in assets] == ["complete", "composed", "generated"]
    assert assets[1].asset_ids == ["primitive.axes", "primitive.labels"]
    assert assets[2].asset_ids == ["primitive.generic"]


def test_cross_domain_visual_routing():
    teaching = TeachingPlan(request=route_topic("数学与历史"), learning_objectives=["关系"], teaching_structure=["比较"],
                            scenes=[sample_scene("math.formula"), sample_scene("general.timeline", Domain.history, "s2")])
    visual = visual_plan(teaching)
    assert [scene.extensions["pack"] for scene in visual.scenes] == ["mathematics", "history"]
    assert visual.scenes[0].extensions["visual_style"]["background"] != visual.scenes[1].extensions["visual_style"]["background"]
    storyboard = build_storyboard(teaching, visual, AssetRetriever().retrieve(visual))
    assert storyboard.scenes[1].domain == Domain.history


def test_secant_viewport_fits_both_points_without_changing_motion():
    scene = sample_scene("math.derivative_secant")
    scene.components[0].parameters = {"x0": 1, "dx_start": 1.6, "dx_end": .05, "x_range": [-.5, 2.5]}
    teaching = TeachingPlan(request=route_topic("导数"), learning_objectives=["变化率"],
                            teaching_structure=["割线到切线"], scenes=[scene])
    visual = visual_plan(teaching)
    params = visual.scenes[0].components[0].parameters
    assert params["x_range"][1] > 2.6
    assert params["dx_start"] == 1.6 and params["x0"] == 1
    assert scene.components[0].parameters["x_range"] == [-.5, 2.5]
    from renderers.base import validate_component
    validate_component("math.derivative_secant", params)


async def test_retrieval_provenance_comes_from_provider():
    def handle(request):
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"pageid": 42}]}})
        return httpx.Response(200, json={"query": {"pages": {"42": {"title": "Derivative", "fullurl": "https://en.wikipedia.org/wiki/Derivative", "extract": "Rate of change."}}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sources = await _wiki_sources("derivative", "en", client)
    assert sources[0]["status"] == "retrieved"
    assert sources[0]["url"] == "https://en.wikipedia.org/wiki/Derivative"
    assert sources[0]["retrieved_at"]


@pytest.mark.parametrize("structured_sequence", [False, True])
async def test_live_plan_preserves_grounded_sources(structured_sequence):
    class Gateway:
        async def generate_json(self, system, prompt):
            assert "不追问用户" in system
            assert "parameters.latex" in system
            request_data = json.loads(prompt)["request"]
            assert request_data["mode"] == "live"
            return {"learning_objectives": ["a"], "teaching_structure": {"sequence": ["a"]} if structured_sequence else ["a"],
                    "scenes": [sample_scene("math.formula").model_dump(mode="json")]}
    request = route_topic("导数", mode="live", duration=25)
    sources = [{"url": "https://example.org/actual-retrieved-source", "status": "retrieved"}]
    teaching = await plan(request, {"knowledge": ["a"], "sources": sources}, Gateway())
    assert teaching.sources == sources
    assert teaching.teaching_structure == ["a"]
    assert teaching.scenes[0].duration == 25


@pytest.mark.parametrize("topic", ["微积分的本质", "导数", "积分", "勾股定理", "牛顿第二定律", "光合作用"])
def test_display_formula_contract_uses_latex(topic):
    lesson = demo_lesson(route_topic(topic))
    formulas = [component["parameters"] for scene in lesson["scenes"] for component in scene["components"]
                if component["id"] == "math.formula"]
    assert formulas
    for params in formulas:
        assert params["latex"]
        assert "formula" not in params
        assert not any(symbol in params["latex"] for symbol in "²³₀₁₂₃∫→")
