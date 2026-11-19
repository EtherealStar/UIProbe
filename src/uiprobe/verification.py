"""Independent visual verification using the framework's output correction loop."""

import asyncio
import json

from pydantic import Field, field_validator
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext
from pydantic_ai.capabilities import Hooks, ProcessHistory
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from .case_input import StrictValue
from .error_handling import LocatedFailure, describe, model_failure_code
from .observability import fact, instrumentation, run_trace
from .observation import AssertionResult, CheckpointSubmission, Status, Verdict
from .recording import SubmissionRecord


class Judgment(StrictValue):
    assertion_id: str
    status: Status
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must describe visible evidence")
        return value


class Judgments(StrictValue):
    results: list[Judgment]


class Verification:
    def __init__(self, model: Model):
        self.model = model

    async def evaluate(
        self,
        submission: CheckpointSubmission,
        deadline_at: float,
        *,
        record: SubmissionRecord,
        request_limit: int,
        retry_limit: int,
    ) -> Verdict:
        if record.submission != submission:
            raise ValueError("Verification record belongs to a different submission")
        with (
            run_trace() as scope,
            scope.tracer.start_as_current_span(
                "verification", attributes=record.association
            ),
        ):
            try:
                return await self._evaluate(
                    submission, deadline_at, record, request_limit, retry_limit
                )
            except LocatedFailure as exc:
                fact("diagnostic", **exc.diagnostic)
                raise
            finally:
                for _, diagnostic in record.failures:
                    fact("diagnostic", **diagnostic)

    async def _evaluate(
        self,
        submission: CheckpointSubmission,
        deadline_at: float,
        record: SubmissionRecord,
        request_limit: int,
        retry_limit: int,
    ) -> Verdict:
        screenshot = submission.screenshot
        history = []

        def save(messages):
            with record.writing("save_verification_history"):
                record.save_messages(messages)

        async def capture(messages):
            history[:] = messages
            save(messages)
            with record.writing("save_verification_requests"):
                record.save_sent_messages(messages)
            if asyncio.get_running_loop().time() >= deadline_at:
                raise TimeoutError
            return messages

        async def after_response(ctx, *, request_context, response):
            messages = [*request_context.messages, response]
            history[:] = messages
            save(messages)
            return response

        agent = Agent(
            self.model,
            output_type=Judgments,
            retries=retry_limit,
            instructions="Judge each assertion using only the screenshot. passed means visible support; failed means visible counterevidence; error means insufficient evidence. Give a nonblank evidence reason.",
            capabilities=[
                ProcessHistory(capture),
                Hooks(after_model_request=after_response),
            ],
        )

        agent.instrument = instrumentation()

        @agent.output_validator
        def validate(ctx: RunContext, output: Judgments) -> Judgments:
            ids = [item.assertion_id for item in output.results]
            if len(ids) != len(set(ids)) or set(ids) != {
                a.id for a in submission.assertions
            }:
                raise ModelRetry(
                    "Return exactly one result for every supplied assertion ID."
                )
            return output

        with record.writing("save_verification_input"):
            record.save_input()
        operation = "check_evidence"
        try:
            if screenshot is None or deadline_at <= asyncio.get_running_loop().time():
                if screenshot is None:
                    raise ValueError("Verification evidence screenshot is missing")
                raise TimeoutError("Verification deadline exhausted")
            operation = "evaluate_assertions"
            async with asyncio.timeout_at(deadline_at):
                result = await agent.run(
                    [
                        json.dumps(
                            {
                                "assertions": [
                                    a.model_dump() for a in submission.assertions
                                ]
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        BinaryContent(data=screenshot.png, media_type="image/png"),
                    ],
                    usage_limits=UsageLimits(request_limit=request_limit),
                )
            history = result.all_messages()
            by_id = {item.assertion_id: item for item in result.output.results}
            assertions = [
                AssertionResult(
                    a.id,
                    by_id[a.id].status,
                    by_id[a.id].reason,
                    screenshot.screenshot_id,
                )
                for a in submission.assertions
            ]
        except LocatedFailure:
            raise
        except Exception as exc:
            error, diagnostic = describe(
                exc,
                "verification",
                operation,
                "evidence_missing" if screenshot is None else model_failure_code(exc),
                f"Visual verification system failed ({type(exc).__name__})",
            )
            diagnostic.update(record.association)
            record.failures.append((error, diagnostic))
            with record.writing("save_verification_failure"):
                record.save_diagnostic(diagnostic)
                record.append({"type": "verification_error", **error.__dict__})
            reason = f"{error.message}; error_id={error.error_id}"
            assertions = [
                AssertionResult(
                    a.id,
                    "error",
                    reason,
                    screenshot.screenshot_id if screenshot else None,
                )
                for a in submission.assertions
            ]
        finally:
            with record.writing("save_verification_history", defer=True):
                record.save_messages(history)
        status: Status = (
            "failed"
            if any(a.status == "failed" for a in assertions)
            else "passed"
            if all(a.status == "passed" for a in assertions)
            else "error"
        )
        return Verdict(submission.submission_id, status, assertions)
