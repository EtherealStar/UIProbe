"""Command-line assembly for a browser test suite."""

import argparse
import asyncio
import json
from dataclasses import asdict
from functools import partial
from pathlib import Path

from .browser import Browser
from .model_service import ModelService, ModelServiceConfig
from .suite_runner import SuiteResult, SuiteRunner


async def run_files(
    case_path: Path, config_path: Path, *, headed: bool = False
) -> SuiteResult:
    return await SuiteRunner(
        lambda: ModelService(ModelServiceConfig.from_env()),
        browser_factory=partial(Browser, headless=not headed),
    ).run(case_path, config_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a screenshot-driven browser test suite. Exit: passed=0, failed=1, error=2."
    )
    parser.add_argument(
        "--case",
        type=Path,
        required=True,
        help='JSON with one case object or a batch object {"cases": [...]}',
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Suite configuration JSON; models use environment or .env",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the controlled browser window; requires a graphical display",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(run_files(args.case, args.config, headed=args.headed))
    print(
        json.dumps(
            asdict(result), ensure_ascii=False, default=lambda value: value.model_dump()
        )
    )
    return {"passed": 0, "failed": 1, "error": 2}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
