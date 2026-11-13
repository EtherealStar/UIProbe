"""Native tools and the shared browser dispatch boundary."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

if TYPE_CHECKING:
    from .agent import Context
from pydantic import Field, field_validator
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset, WrapperToolset

from .browser import Browser, BrowserRejected
from .case_input import StrictValue
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
    async def call_tool(self, name, tool_args, ctx, tool):
        d = ctx.deps
        started = asyncio.get_running_loop().time()
        input_id = d.context.browser_state.screenshot.screenshot_id
        event = {"call_id": ctx.tool_call_id, "tool": name}
        d.record.append({"type": "tool_started", **event})
        try:
            if (tool.tool_def.metadata or {}).get("refresh_browser_state"):
                if not d.context.plan_created:
                    raise ModelRetry("Create a nonempty TODO before browser actions")
                result = await super().call_tool(name, tool_args, ctx, tool)
                state = await d.browser.capture(d.budget.deadline_at)
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
            d.record.append({"type": "tool_finished", "status": "rejected", **event})
            raise ModelRetry(str(exc)) from None
        except BaseException:
            d.record.append(
                {
                    "type": "tool_finished",
                    "status": "error",
                    "action_index": d.budget.action_count,
                    **event,
                }
            )
            raise
        d.record.append(
            {"type": "tool_finished", "status": "completed", **event, **result}
        )
        return result
