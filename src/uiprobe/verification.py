"""Independent visual verification using the framework's output correction loop."""

import asyncio
import time

from pydantic import Field, field_validator
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext
from pydantic_ai.capabilities import Hooks, ProcessHistory
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from .case_input import StrictValue, TestCase
from .observation import AssertionResult, Screenshot, Status, Verdict
from .recording import SessionRecord


class VerificationRecordingError(OSError):
    """Local verification evidence could not be saved."""


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
        test_case: TestCase,
        evidence_screenshot: Screenshot | None,
        deadline_at: float,
        *,
        record: SessionRecord,
        request_limit: int,
        retry_limit: int,
    ) -> Verdict:
        screenshot = evidence_screenshot
        history = []

        def save(messages):
            try:
                record.save_messages("verification", messages, screenshot)
            except OSError as exc:
                raise VerificationRecordingError from exc

        async def capture(messages):
            history[:] = messages
            save(messages)
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

        @agent.output_validator
        def validate(ctx: RunContext, output: Judgments) -> Judgments:
            ids = [item.assertion_id for item in output.results]
            if len(ids) != len(set(ids)) or set(ids) != {
                a.id for a in test_case.assertions
            }:
                raise ModelRetry(
                    "Return exactly one result for every supplied assertion ID."
                )
            return output

        record.save_verification_input(test_case, screenshot)
        reason = "Visual verification unavailable"
        try:
            if screenshot is None or deadline_at <= time.monotonic():
                raise TimeoutError
            async with asyncio.timeout_at(deadline_at):
                result = await agent.run(
                    [
                        test_case.model_dump_json(include={"assertions"}),
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
                for a in test_case.assertions
            ]
        except VerificationRecordingError:
            raise
        except Exception:
            assertions = [
                AssertionResult(
                    a.id,
                    "error",
                    reason,
                    screenshot.screenshot_id if screenshot else None,
                )
                for a in test_case.assertions
            ]
        finally:
            record.save_messages("verification", history, screenshot)
        status: Status = (
            "failed"
            if any(a.status == "failed" for a in assertions)
            else "passed"
            if all(a.status == "passed" for a in assertions)
            else "error"
        )
        return Verdict(status, assertions)
