"""Rebuild original, deterministic History Pack sounds and resource cards.

Uses only the Python standard library. No recordings, external sound bank,
generation service, or topic-specific story is included. Run from any directory.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RATE = 48000
VERSION = "history-original-synthesis-v1"
SPECS = [
    ("footstep", .26, 601, -10, "轻短脚步：人物开始行走；每个提示只触发一次"),
    ("hoof", .40, 607, -12, "双蹄敲击：骑乘或商队移动的单次提示"),
    ("gate", .65, 613, -13, "木门开合的低频摩擦与轻扣；非历史实录"),
    ("paper", .48, 617, -12, "纸页轻摩擦：文书交接、展开与收起"),
    ("stamp", .32, 619, -10, "印章落下的短促木质撞击"),
    ("wind", .80, 631, -19, "短促柔和风声：环境转入，不作为持续底噪"),
    ("draw", .42, 641, -14, "轻柔划线：当前地图连线或图形描画"),
    ("tap", .16, 643, -14, "轻点击：关键词和当前日期强调"),
    ("drum", .55, 647, -14, "低沉短鼓点：章节转折或动作落点"),
    ("chime", .80, 653, -16, "短柔和双音：信息揭示与段落收束"),
]


def synthesize(kind: str, duration: float, seed: int) -> array:
    rng = random.Random(seed)
    samples, low = [], 0.0
    for index in range(round(duration * SAMPLE_RATE)):
        t = index / SAMPLE_RATE
        noise = rng.uniform(-1, 1)
        low = .94 * low + .06 * noise
        x = t / duration
        edge = min(1, t / .006, (duration - t) / .012)
        if kind in {"footstep", "stamp", "drum", "tap", "hoof"}:
            offsets = [0.02, .17] if kind == "hoof" else [.035 if kind == "stamp" else .012]
            value = 0.0
            for at in offsets:
                u = t - at
                if u < 0:
                    continue
                freq = {"footstep": 145, "stamp": 105, "drum": 66, "tap": 680, "hoof": 260}[kind]
                decay = 20 if kind != "drum" else 10
                env = min(1, u / .005) * math.exp(-u * decay)
                value += env * (.65 * math.sin(2 * math.pi * (freq * u + 40 * u * math.exp(-u * 30)))
                                + .30 * noise * math.exp(-u * 50))
        elif kind == "chime":
            value = min(1, t / .025) * math.exp(-t * 6) * (
                .60 * math.sin(2 * math.pi * 784 * t) + .30 * math.sin(2 * math.pi * 1176 * t))
        elif kind == "gate":
            env = math.sin(math.pi * x) ** 1.4
            value = env * (.45 * low + .15 * math.sin(2 * math.pi * (85 * t + 28 * t * t))
                           + .15 * noise * (.5 + .5 * math.sin(2 * math.pi * 19 * t)))
        elif kind == "paper":
            value = math.sin(math.pi * x) ** 1.5 * (noise - low) * (
                .15 + .25 * math.sin(2 * math.pi * 7 * t) ** 2)
        elif kind == "wind":
            value = math.sin(math.pi * x) ** 2 * low
        else:  # draw: dry filtered noise with a soft, varying contact envelope.
            value = math.sin(math.pi * x) ** 1.3 * (noise - low) * (
                .12 + .08 * math.sin(2 * math.pi * 37 * t))
        samples.append(value * max(0, edge))
    peak = max(abs(value) for value in samples) or 1
    return array("h", [round(value / peak * 16383) for value in samples])


def write_wave(path: Path, pcm: array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = array("h", pcm)
    if sys.byteorder != "little":
        data.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(data.tobytes())


def build_catalog(root: Path = ROOT) -> dict:
    # The existing data contract carries source attribution and safe map bounds.
    sys.path.insert(0, str(ROOT))
    from harness.history import HistoryMap

    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    base = ["enter", "exit", "move", "emphasize"]
    descriptions = {
        "actor.person": ("通用古风人物剪影；不宣称具体人物容貌或朝代服饰复原", ["walk", "handover"]),
        "actor.envoy": ("持节使者示意；身份由来源支持的标签说明", ["walk", "handover"]),
        "actor.horse": ("骑者与马的纸本剪影；骑行动作表现位移", ["walk", "ride"]),
        "actor.caravan": ("商队群组示意；不声称确切人数与动物构成", ["walk", "ride"]),
        "prop.gate": ("通用城门示意；支持开闭，不还原特定建筑", ["open", "close"]),
        "prop.document": ("文书物件；不伪造史料原文", ["handover", "open"]),
        "prop.flag": ("无史实纹章的通用旗帜示意", ["draw"]),
        "prop.scroll": ("纸卷；用于逐步揭示当前信息", ["unroll", "open", "close"]),
        "prop.seal": ("通用印章物件；落印为叙事强调，不伪造历史印文", ["stamp"]),
        "info.map": ("仅当前两端点的自然地理地图与示意连线；禁止作为古代国界或精确行程", ["draw"]),
        "info.timeline": ("当前一个经来源核实的日期；未来事件不预先显示", ["draw"]),
        "info.portrait": ("人物符号与姓名身份；示意而非生前肖像或历史照片", []),
    }
    uses = {
        "actor.person": (["人物", "行旅", "交接"], "旁白涉及人物的行动或参与关系，且不需要声称特定身份服饰。", "prop.document", "handover"),
        "actor.envoy": (["使者", "命令", "行旅", "交接"], "资料明确支持使者或传达命令的身份；外形仅作通用示意。", "prop.document", "handover"),
        "actor.horse": (["骑乘", "行旅"], "旁白有据地涉及骑行；不得用骑者外观替代历史肖像。", "prop.gate", "ride"),
        "actor.caravan": (["商队", "行旅", "交流"], "资料支持群体交通或商旅，不把通用群组画成确定人数。", "prop.flag", "walk"),
        "prop.gate": (["城门", "抵达", "离开"], "城门开闭或入城离城是当前旁白含义；建筑仅为环境示意。", "actor.person", "open"),
        "prop.document": (["文书", "交接", "命令"], "旁白涉及文书、消息或命令；图形不承载伪造原文。", "actor.envoy", "handover"),
        "prop.flag": (["标识", "命令", "行旅"], "需要通用方向或群组标识；不得暗示未经证实的国旗、军旗和纹章。", "actor.caravan", "draw"),
        "prop.scroll": (["文书", "揭示", "时序"], "需要逐步展开当前一条有来源的信息；不预告后续事实。", "info.timeline", "unroll"),
        "prop.seal": (["命令", "文书", "强调"], "落印用于当前消息确认或叙事强调，不声称真实印文和印制事件。", "prop.document", "stamp"),
        "info.map": (["地理", "行旅", "交流"], "本轮 geography 至少有两个有据地点，当前仅展示这两个端点。", "actor.person", "draw"),
        "info.timeline": (["时序", "年代", "揭示"], "当前旁白涉及有来源的一个日期，保留约数、世纪或纪年分歧标签。", "prop.scroll", "draw"),
        "info.portrait": (["人物", "身份", "关系"], "旁白需识别有来源的人物姓名与角色，只显示符号而非虚构肖像。", "prop.document", "emphasize"),
    }
    sizes = {"actor.person": (110, 210), "actor.envoy": (110, 220), "actor.horse": (260, 220),
             "actor.caravan": (340, 230), "prop.gate": (440, 340), "prop.document": (150, 145),
             "prop.flag": (140, 240), "prop.scroll": (360, 200), "prop.seal": (140, 200),
             "info.map": (760, 370), "info.timeline": (700, 200), "info.portrait": (220, 280)}
    map_schema = HistoryMap.model_json_schema(by_alias=True)
    map_schema["properties"]["locations"]["maxItems"] = 2
    map_schema["properties"]["source_ids"]["minItems"] = 1
    map_schema["required"].append("source_ids")
    source_ids = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12}
    timeline = {"type": "object", "additionalProperties": False, "properties": {
        "year": {"type": "number", "minimum": -10000, "maximum": 10000, "not": {"const": 0}},
        "date_label": {"type": "string", "minLength": 1, "maxLength": 40},
        "label": {"type": "string", "minLength": 1, "maxLength": 56}, "source_ids": source_ids},
        "required": ["year", "date_label", "label", "source_ids"]}
    portrait = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 56},
        "role": {"type": "string", "minLength": 1, "maxLength": 56}, "source_ids": source_ids},
        "required": ["name", "role", "source_ids"]}
    visuals = []
    for asset_id, (description, actions) in descriptions.items():
        parameters = {"info.map": map_schema, "info.timeline": timeline,
                      "info.portrait": portrait}.get(asset_id, empty)
        intents, condition, companion, demonstration = uses[asset_id]
        example = ("在当前旁白提示处展示；必填事实参数从本次 research 填入，不能照抄虚构示例。"
                   if asset_id.startswith("info.") else
                   {"id": "object_1", "asset_id": asset_id, "x": .5, "y": .70, "scale": 1,
                    "facing": 1, "label": "", "parameters": {}})
        visuals.append({"id": asset_id, "kind": asset_id.split(".")[0], "description": description,
                        "actions": base + actions, "parameters": parameters,
                        "geometry": {"width": sizes[asset_id][0], "height": sizes[asset_id][1],
                                     "anchor": "bottom_center", "label_bottom": 32},
                        "intents": intents, "conditions": [condition, "仅绑定当前讲稿的真实词时间提示，事实须有本轮来源。"],
                        "combination_example": {"resource_ids": [asset_id, companion],
                                                "focus_resource": asset_id, "action": demonstration,
                                                "layout": {"focus": {"x": .42, "y": .70},
                                                           "companion": {"x": .68, "y": .70}},
                                                "note": "只说明可组合能力；人物、信息与先后顺序由本轮 Agent 决定。"},
                        "example": example,
                        "license": "project-original", "source": "renderers/remotion/project/src/HistoryAssets.tsx"})
    sounds = []
    for kind, duration, seed, gain, description in SPECS:
        path = root / "assets" / "audio" / "history" / f"{kind}.wav"
        pcm = synthesize(kind, duration, seed)
        write_wave(path, pcm)
        peak_index = max(range(len(pcm)), key=lambda i: abs(pcm[i]))
        onset_index = next(i for i, value in enumerate(pcm) if abs(value) >= 164)
        sound_intents = {"footstep": ["行旅", "人物"], "hoof": ["骑乘", "行旅"], "gate": ["城门", "抵达"],
                         "paper": ["文书", "交接"], "stamp": ["命令", "强调"], "wind": ["环境", "行旅"],
                         "draw": ["地理", "揭示"], "tap": ["时序", "强调"], "drum": ["转折", "命令"],
                         "chime": ["揭示", "收束"]}
        sounds.append({"id": f"sfx.{kind}", "path": path.relative_to(root).as_posix(),
                       "duration": len(pcm) / SAMPLE_RATE, "onset": onset_index / SAMPLE_RATE,
                       "peak": peak_index / SAMPLE_RATE, "default_gain_db": gain,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "license": "project-original", "description": description,
                       "intents": sound_intents[kind],
                       "conditions": ["当前语义拍有相符的动作或信息揭示。", "遵守最终每分钟12–18次触发预算，不能替代旁白或BGM。"],
                       "provenance": {"method": VERSION, "seed": seed, "sample_rate": SAMPLE_RATE,
                                      "channels": 1, "sample_width": 2,
                                      "generator": "tools/build_history_resources.py",
                                      "recordings_or_external_samples": False},
                       "onset_definition": "first sample at least -40 dBFS",
                       "peak_definition": "first maximum absolute PCM sample"})
    environment_intents = {"mountains": ["环境", "行旅"], "road": ["行旅", "交接"],
                           "desert": ["环境", "行旅"], "city_gate": ["城门", "抵达"],
                           "interior": ["命令", "文书", "交接"], "map": ["地理", "交流"]}
    return {"schema_version": "2.0", "environments": [
        {"id": key, "description": text, "license": "project-original", "intents": environment_intents[key],
         "conditions": ["环境符合本轮资料与讲稿，不把装饰背景当作具体遗址复原。"]} for key, text in [
            ("mountains", "纸本山峦远景；叙事环境示意"), ("road", "平缓道路与远景；旅行场景"),
            ("desert", "沙丘远景；不得以此推断具体地点地貌"), ("city_gate", "通用城郭远景"),
            ("interior", "纸本室内与案几背景"), ("map", "自然地理图面；无现代或古代行政边界")]],
        "visual_assets": visuals, "sfx_assets": sounds,
        "rights": "Original project-drawn symbols and procedurally synthesized sounds; no third-party media.",
        "generation": {"script": "tools/build_history_resources.py", "version": VERSION,
                       "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = build_catalog(root)
    path = root / "assets" / "history" / "animation_resources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(catalog['sfx_assets'])} original sounds and {len(catalog['visual_assets'])} resource cards.")


if __name__ == "__main__":
    main()
