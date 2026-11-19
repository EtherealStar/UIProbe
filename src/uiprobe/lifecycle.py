"""Wait for owned work to settle while retaining the caller's cancellation."""

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from contextvars import copy_context
from threading import Thread
from typing import Any, TypeVar

T = TypeVar("T")
FINALIZATION_SECONDS = 5


def start_background_work(function: Callable[..., T], /, *args) -> asyncio.Future[T]:
    """Allow a slow synchronous operation to outlive the event loop."""
    context = copy_context()
    work: Future[T] = Future()

    def execute():
        if not work.set_running_or_notify_cancel():
            return
        try:
            work.set_result(context.run(function, *args))
        except BaseException as exc:
            work.set_exception(exc)

    # asyncio.run joins its default executor, even after an await has timed out.
    Thread(target=execute, daemon=True).start()
    return asyncio.wrap_future(work)


async def settle(
    work: asyncio.Future[T],
    on_cancel: Callable[[asyncio.CancelledError], None],
    *,
    deadline: float | None = None,
) -> T:
    while not work.done():
        remaining = (
            None if deadline is None else deadline - asyncio.get_running_loop().time()
        )
        try:
            done, _ = await asyncio.wait((work,), timeout=remaining)
        except asyncio.CancelledError as exc:
            on_cancel(exc)
        else:
            if not done:
                # The worker may finish after the caller returns.
                work.add_done_callback(_consume_exception)
                raise TimeoutError
    return work.result()


async def close_within_deadline(
    close: Coroutine[Any, Any, None], timeout: float
) -> None:
    task = asyncio.create_task(close)
    done, _ = await asyncio.wait((task,), timeout=timeout)
    if not done:
        task.add_done_callback(_consume_exception)
        task.cancel()
        raise TimeoutError
    task.result()


def _consume_exception(work: asyncio.Future) -> None:
    if not work.cancelled():
        work.exception()
