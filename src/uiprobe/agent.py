"""Framework execution from the initial browser observation."""

import asyncio
import json
from dataclasses import dataclass, field, replace

from openai import AsyncOpenAI
from pydantic_ai import Agent as FrameworkAgent
from pydantic_ai import BinaryContent
from pydantic_ai.capabilities import Hooks, ProcessHistory
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from .actions import ActionToolset, Dependencies, RunBudget, TodoItem, tools
from .browser import Browser
from .case_input import TestCase
from .error_handling import LocatedFailure, describe, model_failure_code
from .observability import fact, instrumentation, traced
from .observation import BrowserState, Submission
from .recording import SessionRecord


class StreamingModel(WrapperModel):
    """Use native stream assembly before handing a complete turn to the agent."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters
        ) as stream:
            try:
                async for _ in stream:
                    pass
            except BaseException as exc:
                partial = stream.get()
                partial_output = ModelMessagesTypeAdapter.dump_json([partial]).decode()
                setattr(exc, "uiprobe_partial_output", partial_output)
                raise
            return stream.get()


def model_from_client(client: AsyncOpenAI, model_name: str) -> Model:
    """Borrow the application-owned SDK client without changing its lifetime."""
    return StreamingModel(
        OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))
    )


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

    @traced("execution")
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
        feedback_seen: set[int] = set()

        def feedback(messages):
            for message in messages:
                if isinstance(message, ModelRequest):
                    for part in message.parts:
                        if (
                            isinstance(part, RetryPromptPart)
                            or (
                                isinstance(part, ToolReturnPart)
                                and part.outcome == "retried"
                            )
                        ) and id(part) not in feedback_seen:
                            feedback_seen.add(id(part))
                            event = {
                                "type": "tool_feedback",
                                "call_id": part.tool_call_id,
                                "tool": part.tool_name,
                                "reason": part.model_response()
                                if isinstance(part, RetryPromptPart)
                                else part.content,
                            }
                            record.append(event)
                            fact(
                                "tool_feedback",
                                **{
                                    k: (
                                        json.dumps(v)
                                        if isinstance(v, (list, dict))
                                        else v
                                    )
                                    for k, v in event.items()
                                    if v is not None
                                },
                            )

        async def capture(messages: list[ModelMessage]) -> list[ModelMessage]:
            nonlocal seen
            if asyncio.get_running_loop().time() >= deadline_at:
                raise TimeoutError
            feedback(messages)
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
            record.save_sent_messages("execution", view, state.screenshot)
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
        agent.instrument = instrumentation()

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
                            feedback(run.all_messages())
                    finally:
                        context.history.extend(run.all_messages()[seen:])
                        with record.writing("save_tool_feedback"):
                            feedback(run.all_messages())
                    result = run.result
                    assert result is not None
            return Submission(result.output)
        except Exception as exc:
            if not isinstance(exc, LocatedFailure):
                error, diagnostic = describe(
                    exc,
                    "execution",
                    "execute_agent",
                    model_failure_code(exc),
                    f"Execution failed: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
                )
                setattr(exc, "uiprobe_failure", (error, diagnostic))
            raise
        finally:
            with record.writing("save_execution_history"):
                record.save_messages(
                    "execution", context.history, context.browser_state.screenshot
                )
