"""Native tools and the shared browser dispatch boundary."""

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from pydantic_core import to_jsonable_python

if TYPE_CHECKING:
    from .agent import Context
from pydantic import Field, field_validator
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset, WrapperToolset

from .browser import Browser, BrowserRejected
from .case_input import StrictValue
from .error_handling import LocatedFailure, describe
from .observability import fact
from .recording import SessionRecord


class TodoItem(StrictValue):
    description: str
    status: Literal["pending", "in_progress", "completed"]

    @field_validator("description")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Description must not be blank")
        return value


@dataclass
class RunBudget:
    deadline_at: float
    max_actions: int
    action_count: int = 0

    def claim_browser_action(self):
        if asyncio.get_running_loop().time() >= self.deadline_at:
            raise TimeoutError
        if self.action_count >= self.max_actions:
            raise ModelRetry("Browser action budget exhausted")
        self.action_count += 1
        fact(
            "browser_dispatch",
            action_index=self.action_count,
            remaining_seconds=self.deadline_at - asyncio.get_running_loop().time(),
        )
        return self.action_count


@dataclass
class Dependencies:
    context: "Context"
    browser: Browser
    budget: RunBudget
    record: SessionRecord


tools = FunctionToolset[Dependencies]()
Coordinate = Annotated[int, Field(strict=True, ge=0)]
Integer = Annotated[int, Field(strict=True)]
Duration = Annotated[int, Field(strict=True, gt=0)]


@tools.tool(metadata={"refresh_browser_state": False})
async def replace_todo(ctx: RunContext[Dependencies], items: list[TodoItem]) -> dict:
    """Replace the entire TODO plan; create a nonempty plan before browser actions."""
    context = ctx.deps.context
    if sum(item.status == "in_progress" for item in items) > 1:
        raise ModelRetry("At most one TODO can be in progress")
    if not context.plan_created and not items:
        raise ModelRetry("Create a nonempty plan first")
    context.todo = items
    context.plan_created = True
    return {"todo": [item.model_dump() for item in items]}


@tools.tool(sequential=True, metadata={"refresh_browser_state": True})
async def click(
    ctx: RunContext[Dependencies], screenshot_id: str, x: Coordinate, y: Coordinate
) -> dict:
    """Click once at integer pixel coordinates in the current screenshot."""
    d = ctx.deps
    return await d.browser.click(
        screenshot_id, x, y, d.budget.deadline_at, d.budget.claim_browser_action
    )


@tools.tool(sequential=True, metadata={"refresh_browser_state": True})
async def fill_value(ctx: RunContext[Dependencies], ref: str) -> dict:
    """Overwrite the currently focused input with the complete referenced value. Click the target first; supply a reference name, never actual text."""
    d = ctx.deps
    return await d.browser.fill_value(
        ref, d.budget.deadline_at, d.budget.claim_browser_action
    )


@tools.tool(sequential=True, metadata={"refresh_browser_state": True})
async def scroll(ctx: RunContext[Dependencies], delta_y: Integer) -> dict:
    """Scroll the page in CSS pixels: positive down, negative up."""
    d = ctx.deps
    return await d.browser.scroll(
        delta_y, d.budget.deadline_at, d.budget.claim_browser_action
    )


@tools.tool(sequential=True, metadata={"refresh_browser_state": True})
async def wait(ctx: RunContext[Dependencies], duration_ms: Duration) -> dict:
    """Wait 1 to 10000 milliseconds within the remaining session time."""
    d = ctx.deps
    return await d.browser.wait(
        duration_ms, d.budget.deadline_at, d.budget.claim_browser_action
    )


class ActionSummary(TypedDict, total=False):
    tool: str
    input_screenshot_id: str
    screenshot_id: str
    action_index: int
    elapsed_seconds: float


class ActionToolset(WrapperToolset[Dependencies]):
    async def get_tools(self, ctx):
        if ctx.deps.budget.action_count >= ctx.deps.budget.max_actions:
            return {}
        return await super().get_tools(ctx)

    async def call_tool(self, name, tool_args, ctx, tool):
        d = ctx.deps
        started = asyncio.get_running_loop().time()
        input_id = d.context.browser_state.screenshot.screenshot_id
        event = {
            "call_id": ctx.tool_call_id,
            "tool": name,
            "arguments": to_jsonable_python(tool_args),
        }
        fact(
            "tool_started",
            call_id=ctx.tool_call_id or "",
            tool=name,
            arguments=json.dumps(to_jsonable_python(tool_args)),
            input_screenshot_id=input_id,
        )
        d.record.append({"type": "tool_started", **event})
        operation = name
        try:
            if asyncio.get_running_loop().time() >= d.budget.deadline_at:
                raise TimeoutError
            if d.budget.action_count >= d.budget.max_actions:
                raise ModelRetry("Action budget exhausted; summarize and submit")
            if (tool.tool_def.metadata or {}).get("refresh_browser_state"):
                if not d.context.plan_created:
                    raise ModelRetry("Create a nonempty TODO before browser actions")
                result = await super().call_tool(name, tool_args, ctx, tool)
                operation = "capture_after_action"
                state = await d.browser.capture(d.budget.deadline_at)
                operation = "save_action_screenshot"
                d.record.save_screenshot(state.screenshot)
                d.context.browser_state = state
                summary = ActionSummary(
                    tool=name,
                    input_screenshot_id=input_id,
                    elapsed_seconds=asyncio.get_running_loop().time() - started,
                )
                result.update(summary)
                result.update(
                    screenshot_id=state.screenshot.screenshot_id,
                    action_index=d.budget.action_count,
                )
            else:
                result = await super().call_tool(name, tool_args, ctx, tool)
        except (BrowserRejected, ModelRetry) as exc:
            d.record.append(
                {
                    "type": "tool_finished",
                    "status": "rejected",
                    "reason": str(exc),
                    **event,
                }
            )
            fact(
                "tool_rejected",
                reason=str(exc),
                call_id=ctx.tool_call_id or "",
                tool=name,
            )
            raise ModelRetry(str(exc)) from None
        except Exception as exc:
            error, diagnostic = describe(
                exc,
                "recording" if operation == "save_action_screenshot" else "execution",
                operation,
                "action_failed",
                f"{operation} failed: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
            )
            diagnostic.update(
                call_id=ctx.tool_call_id,
                action_index=d.budget.action_count,
                screenshot_id=input_id,
            )
            d.record.append(
                {
                    "type": "tool_finished",
                    "status": "error",
                    "error_id": error.error_id,
                    "reason": error.message,
                    "action_index": d.budget.action_count,
                    **event,
                }
            )
            raise LocatedFailure(error, diagnostic) from exc
        d.record.append(
            {"type": "tool_finished", "status": "completed", **event, **result}
        )
        fact(
            "tool_result",
            call_id=ctx.tool_call_id or "",
            result=json.dumps(result),
        )
        return result
