"""Run the configured History Agent once, without quality/acceptance validation."""
from __future__ import annotations

import argparse
import asyncio

from verify_history import verify


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--topic", required=True, help="由项目 Agent 独立研究、写稿、导演并生成视频")
    args = parser.parse_args()
    try:
        asyncio.run(verify(args.topic, validate=False))
    except Exception as error:
        print(f"生成失败：{error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
