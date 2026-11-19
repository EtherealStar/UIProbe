import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from input_fixtures import case
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.actions import RunBudget
from uiprobe.agent import Context, ExecutionAgent
from uiprobe.browser import Browser
from uiprobe.case_input import Checkpoint, TestCase
from uiprobe.observation import CheckpointSubmission, Screenshot
from uiprobe.recording import Recorder, SessionRecord


def begin_verification(
    record: SessionRecord, checkpoint: Checkpoint, screenshot: Screenshot | None
):
    evidence = CheckpointSubmission(
        uuid4().hex,
        record.session_id,
        checkpoint.id,
        tuple(checkpoint.assertions),
        screenshot,
    )
    return evidence, record.begin_submission(evidence)


def calls(*items):
    return ModelResponse(
        parts=[
            ToolCallPart(name, args, f"call-{i}-{name}")
            for i, (name, args) in enumerate(items)
        ]
    )


async def run_actions(
    responses, html, *, values=None, max_actions=20, request_limit=20
):
    requests = []

    def respond(messages, info):
        requests.append(messages)
        return (
            responses.pop(0) if responses else ModelResponse(parts=[TextPart("Done")])
        )

    browser = Browser()
    deadline = asyncio.get_running_loop().time() + 30
    budget = RunBudget(deadline, max_actions)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory, "page.html")
        path.write_text(html)
        record = Recorder().begin("run", directory)
        try:
            state = await browser.open(path.as_uri(), values or {}, deadline)
            record.save_screenshot(state.screenshot)
            context = Context(
                TestCase.model_validate(case()).checkpoints[0],
                list(values or {}),
                state,
            )
            submission = await ExecutionAgent(FunctionModel(respond)).execute(
                context,
                record=record,
                deadline_at=deadline,
                request_limit=request_limit,
                retry_limit=8,
                browser=browser,
                budget=budget,
                tool_call_limit=40,
                accept_checkpoint=unexpected_submission,
            )
            history = json.loads((record.directory / "history.json").read_text())
            assert "screenshot" in str(history)
            for observation in record.directory.joinpath("screenshots").iterdir():
                assert observation.read_bytes().startswith(b"\x89PNG")
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


def unexpected_submission(*args):
    raise AssertionError("This execution should not submit a checkpoint")


def finish_execution(info, text="Done"):
    if any(tool.name == "submit_checkpoint" for tool in info.function_tools):
        return calls(("submit_checkpoint", {"checkpoint_id": "home"}))
    return ModelResponse(parts=[TextPart(text)])


async def submit_and_finish(context, *, accept_checkpoint, **kwargs):
    from uiprobe.observation import ExecutionOutcome

    accept_checkpoint(context.checkpoint.id, context.browser_state.screenshot)
    return ExecutionOutcome("Done")
