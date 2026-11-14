import asyncio
from pathlib import Path
from threading import Event

import pytest
from filelock import FileLock, Timeout

import harness.orchestrator as orchestration
from harness.orchestrator import Orchestrator
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


class ForbiddenGateway:
    async def generate_json(self, *_):
        raise AssertionError("Demo/checkpoint recovery must not consume model credits")


class FakeRenderer:
    def __init__(self, settings):
        assert settings.tts_enabled is False, "This fixture explicitly requests silent rendering"

    def generate(self, plan, output_dir):
        assert plan.scenes and all(scene.renderer == "canvas" for scene in plan.scenes)
        path = output_dir / "scenes" / "scene_01.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text("# Generated scene fixture\n", encoding="utf-8")
        return [path]

    async def render(self, plan, output_dir):
        final = output_dir / "final.mp4"
        final.write_bytes(b"test-rendered-video" * 16)
        return final


@pytest.fixture
def production(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path / "outputs", minimax_api_key="tts-test-secret",
                        model_api_key="model-test-secret", api_token="api-test-secret")
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="微积分的本质", mode="demo", renderer="canvas", duration=10, tts_enabled=False))
    yield settings, repository, job
    repository.close()


async def test_demo_runs_all_stages_and_registers_artifacts(production):
    settings, repository, job = production
    result = await Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=FakeRenderer).run(job.id)
    assert result.status == "succeeded", result.error
    assert result.progress == 1
    assert Path(result.output_path).read_bytes() == b"test-rendered-video" * 16
    assert {"video_request.json", "research.json", "teaching_plan.json", "visual_plan.json",
            "asset_manifest.json", "storyboard.json", "video_plan.json", "scenes/scene_01.py", "final.mp4"} <= result.artifacts.keys()
    assert all(Path(value).is_relative_to(settings.output_dir / job.id) for value in result.artifacts.values())
    assert settings.tts_enabled is True, "Demo must not mutate shared settings"


@pytest.mark.parametrize("configured,requested,expected", [
    (True, None, True), (True, False, False), (False, True, True), (False, None, False),
])
async def test_demo_narration_is_independent_of_bundled_content(tmp_path, configured, requested, expected):
    settings = Settings(_env_file=None, output_dir=tmp_path / "outputs", tts_enabled=configured)
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="导数", mode="demo", renderer="canvas", tts_enabled=requested))
    observed = []

    class NarrationRenderer(FakeRenderer):
        def __init__(self, cfg):
            observed.append(cfg.tts_enabled)

    try:
        result = await Orchestrator(settings, repository, gateway=ForbiddenGateway(),
                                    renderer_factory=NarrationRenderer).run(job.id)
        assert result.status == "succeeded", result.error
        assert observed == [expected]
        assert settings.tts_enabled is configured
    finally:
        repository.close()


async def test_render_failure_redacts_secrets_and_resumes_checkpoints(production, monkeypatch):
    settings, repository, job = production

    class FailingRenderer(FakeRenderer):
        async def render(self, *_):
            raise RuntimeError("render failed model-test-secret tts-test-secret api-test-secret")

    failed = await Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=FailingRenderer).run(job.id)
    assert failed.status == "failed"
    assert failed.stage == "rendering"
    assert "secret" not in failed.error
    assert "[REDACTED]" in failed.error
    work = settings.output_dir / job.id
    checkpoint_mtimes = {path.name: path.stat().st_mtime_ns for path in work.glob("*.json") if path.name != "video_plan.json"}

    def forbidden(*_, **__):
        raise AssertionError("Valid planning checkpoints must be reused")

    for function in ("route_topic", "research", "plan", "visual_plan", "build_storyboard"):
        monkeypatch.setattr(orchestration, function, forbidden)
    monkeypatch.setattr(orchestration.AssetRetriever, "retrieve", forbidden)
    resumed = await Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=FakeRenderer).run(job.id)
    assert resumed.status == "succeeded", resumed.error
    assert resumed.error is None
    assert checkpoint_mtimes == {path.name: path.stat().st_mtime_ns for path in work.glob("*.json") if path.name != "video_plan.json"}


@pytest.mark.parametrize("failure", ["missing", "outside", "tiny"])
async def test_invalid_renderer_output_cannot_mark_job_succeeded(production, failure, tmp_path):
    settings, repository, job = production

    class InvalidRenderer(FakeRenderer):
        async def render(self, _, output_dir):
            if failure == "outside":
                path = tmp_path / "other-job.mp4"
                path.write_bytes(b"other-video" * 10)
            else:
                path = output_dir / "final.mp4"
                if failure == "tiny":
                    path.write_bytes(b"x")
            return path

    result = await Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=InvalidRenderer).run(job.id)
    assert result.status == "failed"
    assert not result.output_path
    assert "final.mp4" in result.error


async def test_corrupt_upstream_checkpoint_invalidates_dependent_stages(production, monkeypatch):
    settings, repository, job = production
    runner = Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=FakeRenderer)
    initial = await runner.run(job.id)
    assert initial.status == "succeeded"
    work = settings.output_dir / job.id
    unchanged = {name: (work / name).stat().st_mtime_ns for name in ("video_request.json", "research.json")}
    (work / "teaching_plan.json").write_text('{"incomplete":', encoding="utf-8")
    calls = []
    original_plan = orchestration.plan
    original_visual = orchestration.visual_plan
    original_retrieve = orchestration.AssetRetriever.retrieve
    original_storyboard = orchestration.build_storyboard

    async def teaching(*args, **kwargs):
        calls.append("teaching")
        return await original_plan(*args, **kwargs)

    def visual(*args, **kwargs):
        calls.append("visual")
        return original_visual(*args, **kwargs)

    def assets(*args, **kwargs):
        calls.append("assets")
        return original_retrieve(*args, **kwargs)

    def storyboard(*args, **kwargs):
        calls.append("storyboard")
        return original_storyboard(*args, **kwargs)

    monkeypatch.setattr(orchestration, "plan", teaching)
    monkeypatch.setattr(orchestration, "visual_plan", visual)
    monkeypatch.setattr(orchestration.AssetRetriever, "retrieve", assets)
    monkeypatch.setattr(orchestration, "build_storyboard", storyboard)
    result = await runner.run(job.id)
    assert result.status == "succeeded", result.error
    assert calls == ["teaching", "visual", "assets", "storyboard"]
    assert unchanged == {name: (work / name).stat().st_mtime_ns for name in unchanged}


async def test_concurrent_attempts_for_same_job_render_only_once(production):
    settings, repository, job = production
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class ControlledRenderer(FakeRenderer):
        async def render(self, plan, output_dir):
            calls.append(job.id)
            entered.set()
            await release.wait()
            return await super().render(plan, output_dir)

    def runner():
        return Orchestrator(settings, repository, gateway=ForbiddenGateway(), renderer_factory=ControlledRenderer)

    first = asyncio.create_task(runner().run(job.id))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        second = asyncio.create_task(runner().run(job.id))
        await asyncio.sleep(0.05)
        assert not second.done(), "The second attempt must wait for the job lock"
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=4)
        assert [result.status for result in results] == ["succeeded", "succeeded"]
        assert calls == [job.id]
        assert results[0].output_path == results[1].output_path
    finally:
        release.set()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)


async def test_cancelled_sync_renderer_keeps_job_lock_until_thread_exits(production):
    settings, repository, job = production
    entered = Event()
    release = Event()
    finished = Event()

    class ThreadRenderer(FakeRenderer):
        def render(self, _, output_dir):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Test renderer release timed out")
            final = output_dir / "final.mp4"
            final.write_bytes(b"finished-rendering" * 16)
            finished.set()
            return final

    task = asyncio.create_task(Orchestrator(settings, repository, gateway=ForbiddenGateway(),
                                          renderer_factory=ThreadRenderer).run(job.id))
    lock = FileLock(settings.output_dir / job.id / ".production.lock")
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done(), "Cancellation must wait for the encoder thread"
        assert not finished.is_set()
        with pytest.raises(Timeout):
            lock.acquire(timeout=0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        with lock.acquire(timeout=0):
            assert repository.get(job.id).status != "succeeded"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
