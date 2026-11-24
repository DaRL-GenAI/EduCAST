"""CLI entry: python -m educast --request-json request.json"""

from __future__ import annotations

import argparse
from pathlib import Path

from educast.config import Config
from educast.pipeline import (
    load_request,
    run,
    stage1,
    stage2,
    stage2_prepare,
    stage2_render,
    stage2_review,
    stage3,
)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="educast")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--request-json", help="Path to a teaching request JSON")
    source.add_argument(
        "--sample", action="store_true",
        help="Run the bundled algebra lesson, including generation and review/repair",
    )
    p.add_argument("--run-dir", default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="With 2-prepare/2-render/2-review: redo every scene (including passed reviews)",
    )
    p.add_argument(
        "--no-repair",
        action="store_true",
        help="With --stage 2-render: never spend an API call repairing a crashed scene",
    )
    p.add_argument(
        "--stage",
        choices=["all", "1", "2", "2-prepare", "2-render", "2-review", "3"],
        default="all",
        help="Run a single stage or the full pipeline",
    )
    args = p.parse_args(argv)

    request_path = (
        Path(__file__).resolve().parent / "assets" / "sample_request.json"
        if args.sample else Path(args.request_json)
    )
    request = load_request(request_path)
    needs_api = args.stage in {"all", "1", "2", "2-prepare", "2-review"}
    # 2-render only *optionally* uses the key, for repairing a crashed scene.
    cfg = Config.from_env(
        request, run_dir=args.run_dir, require_api_key=needs_api
    )

    if args.stage == "all":
        run(cfg)
    elif args.stage == "1":
        stage1(cfg)
    elif args.stage == "2":
        stage2(cfg)
    elif args.stage == "2-prepare":
        stage2_prepare(cfg, force=args.force)
    elif args.stage == "2-render":
        stage2_render(cfg, force=args.force, repair_crashes=not args.no_repair)
    elif args.stage == "2-review":
        stage2_review(cfg, force=args.force)
    elif args.stage == "3":
        stage3(cfg)


if __name__ == "__main__":
    main()
