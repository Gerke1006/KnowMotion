"""Canonical Phase 2 metadata, applied after the legacy demo catalog is rebuilt."""
from __future__ import annotations

import json
from pathlib import Path

from harness.history import CONTRACTS


RULES = """# History Pack · 历史教学规划

目标是先建立时空背景，再说明人物与事件，最后区分事实、影响与解释。每幕只推进一个核心关系。

## 事实与史料

- 所有明确年代、人物身份、事件和路线关系须有研究资料中的证据；组件 source_ids 只引用输入资料的 id，不能自造来源 URL。
- 同一事件有不同纪年时，优先写可证实的世纪/时期，或注明采用哪个来源；不把争议抹平为唯一精确年份。
- 时间相邻不等于因果，不能把一位人物描绘为独自创造长期交流网络。
- 地理底图只提供陆地空间背景，禁止把现代国界当成古代疆界。地点使用现代近似定位；路线必须标注“示意”，不能声称是复原的精确行程。
- 人物肖像只使用资料明确提供的许可素材。未提供画像时用姓名标记或人物符号，并标注“人物符号示意”，不得生成拟真历史肖像冒充史料。
- dates 采用历史纪年：负数为公元前，正数为公元后，没有公元 0 年。大约年代需在 label/detail/note 中明确“约”。

## 组件与导演约束

历史 live 场景使用 remotion，每幕仅一个主要组件。有至少两个与主题相关且来源可追溯的坐标时，短片应在四幕中覆盖 history.map、history.timeline、history.person，再用其中一个收束。没有可靠坐标时使用时间线与人物组件，不硬凑地图，不得退回纯文字标题卡。

- history.map：2–8 个 locations（id、name、lon、lat），0–12 条 routes（from、to、label、kind="schematic"）。位置 id 与经纬度只采用本轮 research.geography 的记录，不从记忆编造坐标，不借用无关丝路地点。位置 id 唯一且路线两端引用已有 id。viewport 可省略；有则必须包含所有地点。位置、路线事实引用输入来源；现代近似坐标不是古代国界或精确行程的证据。
- history.timeline：2–7 个 events（year 数字、label 字符串、detail 字符串），可以有 range=[起年,止年]；只展示有来源的日期。世纪、约数、纪年有异时须填写 date_label（如“公元前139/138年，记载有异”），此时 year 只作排版锚点，画面显示 date_label，不用锚点伪装精确纪年。
- history.person：name、role、years（字符串，不能填数组）、facts（1–4 个短字符串）、related（可选，最多 4 个 name/relation 对象）。生卒年不确定时 years 写活动时期，不编造精确生卒日期。
- 所有组件均包含 source_ids 字符串数组；每个 id 必须来自研究资料。嵌套记录可补充更细的 source_ids。
- 场景标题不超过 20 个汉字，地点/事件标签不超过 12 个汉字，事件 detail 与人物 facts 单项不超过 40 个汉字。旁白用自然中文，完整叙事放 narration，画面只呈现关键证据。

## 视觉方向

参考 motion-showreel 的确定性时间轴、口播先行和连续空间承接，结合档案纸张、铜版地图线条与编辑式拼贴。暖纸底、墨色文字、朱砂重点、黄铜年代标记。每帧只由时间和输入数据决定；地图航线描画、年代推进、人物档案揭示服务于论证，不堆叠装饰转场。

中文宋体，英文 Times New Roman；字幕沿用用户指定的粗体白字深蓝描边。人物与事件标签有足够阅读时间，字幕不与史料页脚争抢空间。

运行时不追问、不加入 AI 审片或循环改稿。验收必须由项目当前配置模型通过完整 live Agent 流程生成文本和分镜，再配音、渲染、混音；本地示例不能替代端到端验收。
"""

STYLE = {
    "id": "archival_motion", "background": "#F3EBDD", "panel": "#FFFCF5",
    "text": "#27241F", "primary": "#A64532", "accent": "#AF884C", "secondary": "#3F655D",
    "font": "SimSun", "english_font": "Times New Roman", "subtitle_font": "Microsoft YaHei",
    "subtitle_weight": "BOLD", "subtitle_outline": "#161044", "safe_margin": .08,
    "motion": {"reveal_seconds": .65, "easing": "smoothstep", "continuous_camera": True,
               "deterministic": True, "timeline": "measured_narration"},
    "texture": "deterministic-paper-and-engraving",
    "principles": ["先时空后因果", "路线为示意", "出处始终可查", "字随旁白推进", "同一帧可复现"],
    "references": [{"title": "Motion Showreel", "url": "https://github.com/ConardLi/garden-skills/blob/main/skills/motion-showreel/README.zh-CN.md",
                    "use": "帧函数、口播时间轴、连续空间承接；原创实现，不复制素材"}],
}


def install_metadata(root: Path):
    """Refresh only History Pack outputs and its entries in the shared catalog."""
    root = Path(root)
    folder = root / "domains" / "history"

    def write(relative, data):
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    pack.update(version="2.0", style=STYLE["id"], preferred_renderer="remotion",
                components=list(CONTRACTS), source_policy="retrieved-evidence-with-stable-ids")
    for keyword in ("张骞", "西域", "郑和", "文艺复兴", "大航海", "historical", "silk roads"):
        if keyword not in pack["keywords"]:
            pack["keywords"].append(keyword)
    write("pack.json", pack)
    (folder / "plan.md").write_text(RULES, encoding="utf-8")
    write("styles/default.json", STYLE)
    write("renderers/default.json", {"preferred": "remotion", "adapters": ["remotion"],
                                      "legacy_demo_adapters": ["canvas"], "fps": 30, "resolution": [1280, 720],
                                      "composition": "KnowledgeScene", "component_contract": "harness/history.py"})
    write("audio/profile.json", {"narration": "minimax", "voice_name": "温润青年", "bgm_gain": .30,
                                "voice_priority": True, "bgm_source": "BGM_PATH 环境变量", "effects": [],
                                "playback_speed": 1.15, "note": "旁白先行；统一倍速后混入用户 BGM，保持原曲节奏。"})
    write("components/registry.json", {"component_ids": list(CONTRACTS), "renderer": "remotion",
                                       "legacy_components": ["general.process", "general.timeline", "general.relationship"],
                                       "implementation": "renderers/remotion/", "validation": "harness/history.py",
                                       "schemas": {name: f"{name.split('.')[1]}.schema.json" for name in CONTRACTS},
                                       "policy": "模型只提供验证后的数据；历史事实引用已取回的史料 id。"})
    for name, contract in CONTRACTS.items():
        write(f"components/{name.split('.')[1]}.schema.json", contract.model_json_schema(by_alias=True))
    catalog_path = root / "assets" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assets = [item for item in catalog["assets"] if item["id"] not in CONTRACTS]
    for name in CONTRACTS:
        assets.append({"id": name, "component_id": name, "kind": "animation", "level": "complete",
                       "domains": ["history"], "scenes": [name.split('.')[1]],
                       "animations": ["reveal", "focus", "trace"], "renderer": ["remotion"],
                       "source": "renderers/remotion/", "license": "project-original", "version": "2.0"})
    catalog["assets"] = assets
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
