"""Command-line assembly for a single browser test session."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .agent import ExecutionAgent, model_from_client
from .model_service import ModelService, ModelServiceConfig
from .session import Session, SessionError, SessionResult
from .verification import Verification


async def run_application(
    test_json: str, config: object, service: ModelService
) -> SessionResult:
    """Borrow the application's client for independent execution and verification."""
    model = model_from_client(service.client, service.config.model)
    return await Session(
        agent=ExecutionAgent(model), verification=Verification(model)
    ).run(test_json, config)


async def run_files(case_path: Path, config_path: Path) -> SessionResult:
    try:
        test_json = case_path.read_text(encoding="utf-8")
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return startup_error("input", "Cannot read case or configuration JSON")
    try:
        connection = ModelServiceConfig.from_env()
        service = ModelService(connection)
    except (ValueError, TypeError):
        return startup_error("configuration", "Invalid or missing model configuration")
    async with service:
        return await run_application(test_json, config, service)


def startup_error(phase: str, message: str) -> SessionResult:
    return SessionResult(
        uuid4().hex,
        stop_reason=phase + "_error",
        errors=[SessionError(phase, "startup_failed", message)],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a screenshot-driven browser test. Exit: passed=0, failed=1, error=2."
    )
    parser.add_argument(
        "--case",
        type=Path,
        required=True,
        help="Test JSON with execution and assertions",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Session configuration JSON; models use environment or .env",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(run_files(args.case, args.config))
    print(
        json.dumps(
            asdict(result), ensure_ascii=False, default=lambda value: value.model_dump()
        )
    )
    return {"passed": 0, "failed": 1, "error": 2}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
