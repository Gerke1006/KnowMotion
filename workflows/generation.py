"""Trusted component compilation entry point."""
from pathlib import Path

from renderers.service import VideoRenderer


def generate(plan, settings, output_dir: Path):
    return VideoRenderer(settings).generate(plan, output_dir)
