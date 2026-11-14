"""Rendering adapter entry point; technical output checks live inside adapters."""
from pathlib import Path

from renderers.service import VideoRenderer


def render(plan, settings, output_dir: Path):
    return VideoRenderer(settings).render(plan, output_dir)
