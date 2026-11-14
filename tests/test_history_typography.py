"""History-only typography and frozen-configuration checks; no rendering or services."""
import json
from pathlib import Path

import pytest

from harness.history_profile import history_settings
from harness.production_audit import FrozenRun
from harness.settings import Settings


@pytest.fixture
def history_config(tmp_path):
    project = tmp_path / "project"
    source = Path(__file__).resolve().parents[1] / "assets/history/production_profile.json"
    target = project / "assets/history/production_profile.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    original = Settings(_env_file=None, project_root=project, bgm_path="",
                        model_name="isolated-model", model_api_key="isolated-key", minimax_api_key="isolated-key",
                        chinese_font="SimSun", subtitle_font="Microsoft YaHei", subtitle_font_weight="BOLD",
                        subtitle_background_opacity=.4, history_narrative_bindings=False)
    return original, json.loads(target.read_text(encoding="utf-8"))


def test_history_profile_applies_typography_and_bindings_without_mutating_other_domains(history_config):
    original, profile = history_config
    before = original.model_dump()
    history = history_settings(original)
    assert history is not original
    assert all(getattr(history, key) == value for key, value in profile["typography"].items())
    assert profile["require_narrative_bindings"] is True
    assert history.history_narrative_bindings is True
    assert original.model_dump() == before
    assert original.chinese_font == "SimSun" and original.subtitle_font == "Microsoft YaHei"
    assert original.history_narrative_bindings is False
    assert history.minimax_voice_id == original.minimax_voice_id
    assert history.playback_speed == original.playback_speed


def test_frozen_history_rejects_font_binary_replacement(history_config, tmp_path):
    original, _ = history_config
    font = original.project_root / "renderers/remotion/project/public/fonts/history-serif-heavy.otf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"OTTO-isolated-font-fixture-A")
    audit = FrozenRun(history_settings(original), tmp_path / "run", "isolated audit topic")
    assert audit.verify()["build_unchanged"]
    font.write_bytes(b"OTTO-isolated-font-fixture-B")
    with pytest.raises(ValueError, match="build changed"):
        audit.verify()


def test_frozen_history_rejects_subtitle_background_opacity_change(history_config, tmp_path):
    original, _ = history_config
    history = history_settings(original)
    audit = FrozenRun(history, tmp_path / "run", "isolated audit topic")
    assert audit.verify()["configuration_unchanged"]
    history.subtitle_background_opacity = .3
    with pytest.raises(ValueError, match="configuration changed"):
        audit.verify()
