"""Isolated adapter contracts; these do not constitute live video acceptance."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

import renderers.remotion as remotion
import renderers.service as service
from renderers.base import RendererError


@pytest.fixture
def installed_project(tmp_path, monkeypatch):
    project = tmp_path / "trusted project 项目"
    for relative, content in {
        "node_modules/@remotion/cli/remotion-cli.js": "// isolated CLI fixture",
        "src/index.ts": "// trusted entry",
        "src/components/HistoryMap.tsx": "// trusted component",
        "public/data/land.geojson": '{"type":"FeatureCollection","features":[]}',
        "package.json": '{"name":"isolated-project"}',
        "package-lock.json": '{"lockfileVersion":3}',
        "remotion.config.ts": "// trusted config",
    }.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(remotion.shutil, "which", lambda name: "isolated-node" if name == "node" else None)
    return project


def simple_scene():
    return {"scene_id": "scene_01", "title": "史料", "duration": 3, "components": []}


def test_default_project_is_bundled_and_can_be_overridden(installed_project, monkeypatch):
    monkeypatch.setattr(remotion, "BUNDLED_PROJECT", installed_project)
    assert remotion.RemotionRenderer().project == installed_project.resolve()
    configured = installed_project / "other project"
    assert remotion.RemotionRenderer({"remotion_project": configured}).project == configured.resolve()


@pytest.mark.parametrize("missing", ["node", "cli", "entry", "browser"])
def test_missing_remotion_dependency_fails_before_narration(installed_project, tmp_path, monkeypatch, missing):
    settings = {"remotion_project": installed_project, "tts_enabled": True, "minimax_api_key": "unit-only"}
    if missing == "node":
        monkeypatch.setattr(remotion.shutil, "which", lambda name: None)
    elif missing == "cli":
        (installed_project / "node_modules/@remotion/cli/remotion-cli.js").unlink()
    elif missing == "entry":
        (installed_project / "src/index.ts").unlink()
    else:
        settings["remotion_browser_executable"] = str(tmp_path / "missing browser.exe")

    def unexpected(*args, **kwargs):
        pytest.fail("Preflight must fail before narration or external execution")

    monkeypatch.setattr(service, "FFmpeg", lambda settings: object())
    monkeypatch.setattr(service.MiniMaxTTS, "synthesize", unexpected)
    monkeypatch.setattr(remotion, "run_command", unexpected)
    scene = {**simple_scene(), "renderer": "remotion", "narration": "仅用于隔离回归。"}
    message = "REMOTION_BROWSER_EXECUTABLE" if missing == "browser" else "Remotion requires"
    with pytest.raises(RendererError, match=message):
        service.VideoRenderer(settings).render({"metadata": {}, "scenes": [scene]}, tmp_path / "output")


def test_preflight_ensures_browser_when_not_configured(installed_project, monkeypatch):
    calls = []
    monkeypatch.setattr(remotion, "run_command", lambda args, **kwargs: calls.append((args, kwargs)))
    renderer = remotion.RemotionRenderer({"remotion_project": installed_project})
    renderer.preflight(ensure_browser=True)
    assert calls == [(
        ["isolated-node", str(installed_project / "node_modules/@remotion/cli/remotion-cli.js"),
         "browser", "ensure", "--log=error"],
        {"cwd": installed_project.resolve(), "timeout": 600},
    )]


def test_props_preserve_untrusted_text_without_execution(installed_project, tmp_path, monkeypatch):
    marker = tmp_path / "should-not-exist"
    dangerous = (
        "中文 \"quoted\" \\ newline\n</script> ${process.exit(1)} `exit` $(exit); "
        f"__import__('pathlib').Path({str(marker)!r}).write_text('executed')"
    )
    scene = {**simple_scene(), "title": dangerous, "narration": dangerous}
    metadata = {"title": dangerous, "width": 1920, "height": 1080}
    settings = {
        "remotion_project": installed_project,
        "chinese_font": "SimSun",
        "english_font": "Times New Roman",
        "subtitle_font": "Microsoft YaHei",
        "subtitle_font_weight": "BOLD",
        "subtitle_color": "#FEFEFE",
        "subtitle_outline_color": "#161044",
        "subtitle_outline_width": 6,
    }

    def unexpected(*args, **kwargs):
        pytest.fail("Generating props must not execute a process")

    monkeypatch.setattr(remotion, "run_command", unexpected)
    path = remotion.RemotionRenderer(settings).generate(scene, metadata, tmp_path / "props")
    props = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "scene_01.remotion.json"
    assert props["scene"] == scene
    assert props["metadata"] == metadata
    assert props["fonts"] == {
        "chinese": "SimSun", "english": "Times New Roman", "subtitle": "Microsoft YaHei",
        "subtitle_weight": "BOLD", "subtitle_color": "#FEFEFE", "outline_color": "#161044",
        "outline_width": 6,
    }
    assert not marker.exists()


def test_history_normalization_preserves_caller_scene_and_sources(installed_project, tmp_path):
    sources = [{"id": "source_01", "title": "Official source", "url": "https://whc.unesco.org/en/list/1442/"}]
    scene = {
        **simple_scene(),
        "extensions": {"historical_sources": sources},
        "components": [{
            "id": "history.timeline", "parameters": {
                "source_ids": ["source_01"],
                "events": [{"year": 100, "label": "较晚"}, {"year": -100, "label": "较早"}],
            },
        }],
    }
    original = copy.deepcopy(scene)
    metadata = {"mode": "live"}
    path = remotion.RemotionRenderer({"remotion_project": installed_project}).generate(scene, metadata, tmp_path)
    props = json.loads(path.read_text(encoding="utf-8"))
    normalized = props["scene"]["components"][0]["parameters"]
    assert [event["year"] for event in normalized["events"]] == [-100, 100]
    assert normalized["note"]
    assert props["sources"] == sources
    assert normalized["source_ids"] == ["source_01"]
    assert scene == original
    assert metadata == {"mode": "live"}


@pytest.mark.parametrize("source_ids", [[], ["unretrieved_source"]])
def test_live_history_rejects_missing_or_unknown_citations(installed_project, tmp_path, source_ids):
    scene = {
        **simple_scene(),
        "extensions": {"historical_sources": [{"id": "source_01"}]},
        "components": [{
            "id": "history.person",
            "parameters": {"name": "人物", "role": "使者", "facts": ["史料陈述"], "source_ids": source_ids},
        }],
    }
    with pytest.raises(ValueError, match="source_ids"):
        remotion.RemotionRenderer({"remotion_project": installed_project}).generate(scene, {"mode": "live"}, tmp_path)
    assert not (tmp_path / "scene_01.remotion.json").exists()


@pytest.mark.parametrize("relative", [
    "src/index.ts", "src/components/HistoryMap.tsx", "public/data/land.geojson",
    "package.json", "package-lock.json", "remotion.config.ts",
])
def test_source_asset_and_package_changes_invalidate_fingerprint(installed_project, relative):
    renderer = remotion.RemotionRenderer({"remotion_project": installed_project})
    before = renderer.fingerprint()
    path = installed_project / relative
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    assert renderer.fingerprint() != before
    path.write_bytes(original)
    assert renderer.fingerprint() == before


def test_node_modules_and_browser_cache_do_not_invalidate_fingerprint(installed_project):
    renderer = remotion.RemotionRenderer({"remotion_project": installed_project})
    before = renderer.fingerprint()
    (installed_project / "node_modules/@remotion/cli/remotion-cli.js").write_text("changed install")
    cache = installed_project / "node_modules/.cache/browser/headless.exe"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"isolated browser cache")
    assert renderer.fingerprint() == before


def test_render_cli_uses_props_file_and_configured_browser(installed_project, tmp_path, monkeypatch):
    browser = tmp_path / "browser with spaces.exe"
    browser.write_bytes(b"isolated browser fixture")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        # A nonempty adapter output sentinel, not a video or E2E acceptance artifact.
        Path(args[5]).write_bytes(b"adapter-output-sentinel" * 3)
        return "isolated render log"

    monkeypatch.setattr(remotion, "run_command", run)
    renderer = remotion.RemotionRenderer({
        "remotion_project": installed_project,
        "remotion_concurrency": 3,
        "remotion_browser_executable": str(browser),
    })
    scene = {**simple_scene(), "title": '"; process.exit(1); //'}
    output = renderer.render(scene, {"fps": 30}, tmp_path / "render output")
    assert len(calls) == 1  # Configured browser avoids a separate browser download.
    args, kwargs = calls[0]
    assert args[:5] == [
        "isolated-node", str(installed_project / "node_modules/@remotion/cli/remotion-cli.js"),
        "render", str(installed_project / "src/index.ts"), "KnowledgeScene",
    ]
    assert args[5] == str(output.resolve())
    props_path = Path(args[args.index("--props") + 1])
    assert props_path.is_absolute() and props_path.is_file()
    assert json.loads(props_path.read_text(encoding="utf-8"))["scene"]["title"] == scene["title"]
    assert scene["title"] not in args
    assert args[args.index("--concurrency") + 1] == "3"
    assert args[args.index("--browser-executable") + 1] == str(browser)
    assert "--codec=h264" in args and "--pixel-format=yuv420p" in args
    assert kwargs == {"cwd": installed_project.resolve()}
    assert (output.parent / "remotion-render.log").read_text(encoding="utf-8") == "isolated render log"


def test_render_requires_nonempty_output(installed_project, tmp_path, monkeypatch):
    monkeypatch.setattr(remotion, "run_command", lambda *args, **kwargs: "no output")
    with pytest.raises(RendererError, match="nonempty file"):
        remotion.RemotionRenderer({"remotion_project": installed_project}).render(simple_scene(), {}, tmp_path)


def test_props_reject_scene_path_traversal(installed_project, tmp_path):
    with pytest.raises(RendererError, match="scene_id"):
        remotion.RemotionRenderer({"remotion_project": installed_project}).generate(
            {**simple_scene(), "scene_id": "../outside"}, {}, tmp_path / "props"
        )
    assert not (tmp_path / "outside.remotion.json").exists()


def test_director_crash_never_reuses_previous_success(installed_project, tmp_path, monkeypatch):
    props, output = tmp_path / "props.json", tmp_path / "report.json"
    props.write_text('{"director":"new props"}', encoding="utf-8")
    output.write_text('{"passed":true}', encoding="utf-8")
    def crash(*args, **kwargs):
        raise RendererError("isolated checker crash")
    monkeypatch.setattr(remotion, "run_command", crash)
    with pytest.raises(RendererError, match="checker crash"):
        remotion.RemotionRenderer({"remotion_project": installed_project}).check_director(props, output)
    assert not output.exists()


@pytest.mark.parametrize("valid", [True, False])
def test_director_report_is_bound_to_exact_props(installed_project, tmp_path, monkeypatch, valid):
    props, output = tmp_path / "props.json", tmp_path / "report.json"
    props.write_text('{"director":"isolated"}', encoding="utf-8")
    digest = hashlib.sha256(props.read_bytes()).hexdigest()
    def check(*args, **kwargs):
        output.write_text(json.dumps({"passed": True, "props_sha256": digest if valid else "stale"}), encoding="utf-8")
        return ""
    monkeypatch.setattr(remotion, "run_command", check)
    renderer = remotion.RemotionRenderer({"remotion_project": installed_project})
    if valid:
        assert renderer.check_director(props, output)["passed"]
    else:
        with pytest.raises(RendererError, match="fingerprint"):
            renderer.check_director(props, output)
