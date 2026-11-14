"""Deterministic decoding, silence and black-frame checks; no AI review."""
import re

from harness.production_audit import save_json
from renderers.ffmpeg import FFmpeg


def inspect_media(folder, report, settings):
    ffmpeg = FFmpeg(settings)
    log = ffmpeg.run(["-i", str(folder / "joined.mp4"), "-af", "silencedetect=noise=-45dB:d=0.02",
                      "-f", "null", "-"])
    silences, start = [], None
    for kind, raw in re.findall(r"silence_(start|end):\s*([0-9.]+)", log):
        if kind == "start":
            start = float(raw)
        elif start is not None:
            silences.append((start, float(raw)))
            start = None
    boundaries = []
    for transition in report["composition"]["transitions"]:
        middle = (transition["start"] + transition["end"]) / 2
        gap = next((b - a for a, b in silences if a - .05 <= middle <= b + .05), 0)
        boundaries.append({"at": middle, "measured_silence": gap})
    black_log = ffmpeg.run(["-i", str(folder / "final.mp4"), "-an", "-vf",
                           "blackdetect=d=0.1:pix_th=0.02:pic_th=0.999", "-f", "null", "-"])
    result = {"boundaries": boundaries,
              "max_boundary_silence": max((b["measured_silence"] for b in boundaries), default=0),
              "black_intervals": len(re.findall(r"black_start:", black_log))}
    save_json(folder / "media_verification.json", result)
    return result
