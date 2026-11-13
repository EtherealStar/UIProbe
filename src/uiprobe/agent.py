"""Framework execution from the initial browser observation."""

import asyncio
import json
from dataclasses import dataclass, field, replace

from openai import AsyncOpenAI
from pydantic_ai import Agent as FrameworkAgent
from pydantic_ai import BinaryContent
from pydantic_ai.capabilities import Hooks, ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from .actions import ActionToolset, Dependencies, RunBudget, TodoItem, tools
from .browser import Browser
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
    todo: list[TodoItem] = field(default_factory=list)
    plan_created: bool = False
    history: list[ModelMessage] = field(default_factory=list)

    def messages_for_model(self) -> list[ModelMessage]:
        view = []
        for message in self.history:
            if isinstance(message, ModelRequest):
                parts = []
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and isinstance(
                        part.content, list
                    ):
                        part = replace(
                            part,
                            content=[
                                item
                                for item in part.content
                                if not isinstance(item, BinaryContent)
                            ],
                        )
                    parts.append(part)
                message = replace(message, parts=parts)
            view.append(message)
        return view


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
        browser: Browser,
        budget: RunBudget,
        tool_call_limit: int,
    ) -> Submission:
        seen = 0

        async def capture(messages: list[ModelMessage]) -> list[ModelMessage]:
            nonlocal seen
            if asyncio.get_running_loop().time() >= deadline_at:
                raise TimeoutError
            context.history.extend(messages[seen:])
            state = context.browser_state
            observation = ModelRequest(
                parts=[
                    UserPromptPart(
                        [
                            f"Current screenshot: {state.screenshot.screenshot_id}; image {state.screenshot.image_width}x{state.screenshot.image_height}; viewport {state.viewport_width}x{state.viewport_height}",
                            BinaryContent(
                                data=state.screenshot.png,
                                media_type="image/png",
                                identifier=state.screenshot.screenshot_id,
                            ),
                        ]
                    )
                ]
            )
            context.history.append(observation)
            if budget.action_count >= budget.max_actions:
                context.history.append(
                    ModelRequest(
                        parts=[
                            UserPromptPart(
                                "Action budget exhausted; all tools disabled. Summarize and submit."
                            )
                        ]
                    )
                )
            record.save_messages("execution", context.history, state.screenshot)
            view = context.messages_for_model()
            view[-2 if budget.action_count >= budget.max_actions else -1] = observation
            seen = len(view)
            return view

        async def after_response(ctx, *, request_context, response):
            nonlocal seen
            context.history.append(response)
            seen = len(request_context.messages) + 1
            record.save_messages(
                "execution", context.history, context.browser_state.screenshot
            )
            return response

        agent = FrameworkAgent(
            self.model,
            deps_type=Dependencies,
            retries=retry_limit,
            toolsets=[ActionToolset(tools)],
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
                async with agent.iter(
                    prompt,
                    deps=Dependencies(context, browser, budget, record),
                    usage_limits=UsageLimits(
                        request_limit=request_limit, tool_calls_limit=tool_call_limit
                    ),
                ) as run:
                    try:
                        async for _ in run:
                            pass
                    finally:
                        context.history.extend(run.all_messages()[seen:])
                    result = run.result
                    assert result is not None
            return Submission(result.output)
        finally:
            record.save_messages("execution", context.history, state.screenshot)
