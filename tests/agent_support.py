import asyncio
import json
import tempfile
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_session_input import case

from uiprobe.actions import RunBudget
from uiprobe.agent import Context, ExecutionAgent
from uiprobe.browser import Browser
from uiprobe.case_input import TestCase
from uiprobe.recording import Recorder


def calls(*items):
    return ModelResponse(
        parts=[
            ToolCallPart(name, args, f"call-{i}-{name}")
            for i, (name, args) in enumerate(items)
        ]
    )


async def run_actions(responses, html, *, values=None):
    requests = []

    def respond(messages, info):
        requests.append(messages)
        return (
            responses.pop(0) if responses else ModelResponse(parts=[TextPart("Done")])
        )

    browser = Browser()
    deadline = asyncio.get_running_loop().time() + 30
    budget = RunBudget(deadline, 20)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory, "page.html")
        path.write_text(html)
        record = Recorder().begin("run", directory)
        try:
            state = await browser.open(path.as_uri(), values or {}, deadline)
            record.save_screenshot(state.screenshot)
            context = Context(
                TestCase.model_validate(case()), list(values or {}), state
            )
            submission = await ExecutionAgent(FunctionModel(respond)).execute(
                context,
                record=record,
                deadline_at=deadline,
                request_limit=20,
                retry_limit=8,
                browser=browser,
                budget=budget,
                tool_call_limit=40,
            )
            assert browser.page is not None
            content = await browser.page.content()
            events = [
                json.loads(line)
                for line in (record.directory / "events.jsonl").read_text().splitlines()
            ]
            return context, budget, submission, content, events, requests
        finally:
            await browser.close()


PLAN = (
    "replace_todo",
    {"items": [{"description": "Operate page", "status": "in_progress"}]},
)
