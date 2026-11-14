"""Command-line assembly for a single browser test session."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .agent import ExecutionAgent, model_from_client
from .error_handling import describe
from .model_service import ModelService, ModelServiceConfig
from .observability import traced
from .recording import Recorder
from .session import Session, SessionResult
from .verification import Verification


@traced("application_session")
async def run_application(
    test_json: str, config: object, service: ModelService
) -> SessionResult:
    """Borrow the application's client for independent execution and verification."""
    model = model_from_client(service.client, service.config.model)
    return await Session(
        agent=ExecutionAgent(model),
        verification=Verification(model),
    ).run(test_json, config)


@traced("startup")
async def run_files(case_path: Path, config_path: Path) -> SessionResult:
    config = None
    operation = "read_config"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        operation = "read_case"
        test_json = case_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return await startup_error(
            "input", "Cannot read case or configuration JSON", exc, operation, config
        )
    try:
        connection = ModelServiceConfig.from_env()
        service = ModelService(connection)
    except (ValueError, TypeError) as exc:
        return await startup_error(
            "configuration",
            "Invalid or missing model configuration",
            exc,
            "configure_model",
            config,
        )
    try:
        return await run_application(test_json, config, service)
    finally:
        await close_service(service)


@traced("model_client.close")
async def close_service(service):
    await service.client.close()


async def startup_error(
    phase: str, message: str, exc: BaseException, operation: str, config: object = None
) -> SessionResult:
    error, diagnostic = describe(
        exc, phase, operation, "startup_failed", f"{message} ({type(exc).__name__})"
    )
    result = SessionResult(uuid4().hex, stop_reason=phase + "_error", errors=[error])
    output_dir = config.get("output_dir") if isinstance(config, dict) else None
    if isinstance(output_dir, str) and output_dir.strip() and chr(0) not in output_dir:
        try:
            record = Recorder().begin(result.session_id, output_dir)
            from .observability import bind_record

            bind_record(record)
        except OSError as recording_exc:
            summary, _ = describe(
                recording_exc,
                "recording",
                "create_record",
                "begin_failed",
                "Cannot create record",
            )
            result.errors.append(summary)
        else:
            try:
                async with asyncio.timeout(5):
                    result = await asyncio.to_thread(
                        Session._finish_record, record, result, False, [diagnostic]
                    )
            except TimeoutError:
                summary, _ = describe(
                    TimeoutError(),
                    "recording",
                    "finalize_record",
                    "finalization_timeout",
                    "Record finalization exceeded deadline",
                )
                result.errors.append(summary)
                result.artifact_paths = [str(record.directory)]
    return result


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
