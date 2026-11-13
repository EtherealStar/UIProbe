"""Framework execution from the initial browser observation."""

import asyncio
import json
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from pydantic_ai import Agent as FrameworkAgent
from pydantic_ai import BinaryContent
from pydantic_ai.capabilities import Hooks, ProcessHistory
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from .case_input import TestCase
from .observation import BrowserState, Submission
from .recording import SessionRecord


def model_from_client(client: AsyncOpenAI, model_name: str) -> Model:
    """Borrow the application-owned SDK client without changing its lifetime."""
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


@dataclass
class Context:
    test_case: TestCase
    ref_names: list[str]
    browser_state: BrowserState
    history: list[ModelMessage] = field(default_factory=list)


class ExecutionAgent:
    def __init__(self, model: Model):
        self.model = model

    async def execute(
        self,
        context: Context,
        *,
        record: SessionRecord,
        deadline_at: float,
        request_limit: int,
        retry_limit: int,
    ) -> Submission:
        async def capture(messages: list[ModelMessage]) -> list[ModelMessage]:
            context.history = list(messages)
            record.save_messages(
                "execution", messages, context.browser_state.screenshot
            )
            return messages

        async def after_response(ctx, *, request_context, response):
            messages = [*request_context.messages, response]
            context.history = messages
            record.save_messages(
                "execution", messages, context.browser_state.screenshot
            )
            return response

        agent = FrameworkAgent(
            self.model,
            retries=retry_limit,
            capabilities=[
                ProcessHistory(capture),
                Hooks(after_model_request=after_response),
            ],
            instructions="Read the test case and browser observation. Return final text when execution is complete. Submission does not establish assertion results.",
        )
        state = context.browser_state
        prompt = json.dumps(
            {
                "test_case": context.test_case.model_dump(),
                "ref_names": context.ref_names,
                "screenshot_id": state.screenshot.screenshot_id,
                "image_width": state.screenshot.image_width,
                "image_height": state.screenshot.image_height,
                "viewport_width": state.viewport_width,
                "viewport_height": state.viewport_height,
            }
        )
        try:
            async with asyncio.timeout_at(deadline_at):
                result = await agent.run(
                    [
                        prompt,
                        BinaryContent(
                            data=state.screenshot.png, media_type="image/png"
                        ),
                    ],
                    usage_limits=UsageLimits(request_limit=request_limit),
                )
            context.history = result.all_messages()
            return Submission(result.output)
        finally:
            record.save_messages("execution", context.history, state.screenshot)
