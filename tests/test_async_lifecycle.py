import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from input_fixtures import case, config

from uiprobe.model_service import ModelServiceConfig
from uiprobe.suite_runner import SuiteRunner


class AsyncLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_waits_for_shared_client_close(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()
        service = AsyncMock()
        service.config = ModelServiceConfig(
            "http://controlled/v1", "test", "controlled"
        )

        async def close():
            entered.set()
            await release.wait()
            closed.set()

        service.close.side_effect = close
        browser_factory = Mock(side_effect=asyncio.CancelledError)
        with tempfile.TemporaryDirectory() as directory:
            task = asyncio.create_task(
                SuiteRunner(lambda: service, browser_factory=browser_factory).run(
                    json.dumps({"cases": [case(), {**case(), "id": "later"}]}),
                    {"defaults": config(directory)},
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            try:
                for _ in range(2):
                    task.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertTrue(closed.is_set())
            trace = next(Path(directory).glob("*/trace.json"))
            snapshot = json.loads(trace.with_name("result.json").read_text())
            self.assertEqual(snapshot["stop_reason"], "cancelled")
            self.assertEqual(
                [item["status"] for item in snapshot["cases"]], ["error", "not_run"]
            )
            self.assertEqual(
                snapshot["cases"][0]["session_result"]["stop_reason"], "cancelled"
            )
            self.assertEqual(snapshot["errors"], [])
            service.close.assert_awaited_once()
            browser_factory.assert_called_once()

    async def test_verification_queue_uses_session_deadline_and_drains_on_cancellation(
        self,
    ):
        from input_fixtures import prepared_case

        from uiprobe.observation import BrowserState, ExecutionOutcome, Screenshot
        from uiprobe.session import Session, SessionCancelled

        for cancel in (False, True):
            with (
                self.subTest(cancel=cancel),
                tempfile.TemporaryDirectory() as directory,
            ):
                active = asyncio.Event()
                released = asyncio.Event()
                closed = asyncio.Event()
                browser = AsyncMock()
                screenshot = Screenshot("screen-1", b"png", 1, 1)

                async def open_browser(entry_url, data_values, deadline_at):
                    deadlines.append(deadline_at)
                    return BrowserState(screenshot, 1, 1)

                async def close_browser():
                    closed.set()

                browser.open.side_effect = open_browser
                browser.close.side_effect = close_browser
                deadlines = []
                agent = AsyncMock()

                async def execute(context, *, deadline_at, accept_checkpoint, **kwargs):
                    deadlines.append(deadline_at)
                    accept_checkpoint("home", screenshot)
                    accept_checkpoint("queued", screenshot)
                    return ExecutionOutcome("Done")

                agent.execute.side_effect = execute
                verification = AsyncMock()

                async def evaluate(submission, deadline_at, **kwargs):
                    deadlines.append(deadline_at)
                    active.set()
                    try:
                        await asyncio.Future()
                    finally:
                        released.set()

                verification.evaluate.side_effect = evaluate
                defaults = config(directory)
                defaults["timeout_seconds"] = 30 if cancel else 0.25
                prepared = prepared_case(defaults)
                checkpoint = prepared.test_case.checkpoints[0]
                prepared.test_case.checkpoints.append(
                    checkpoint.model_copy(update={"id": "queued"})
                )

                task = asyncio.create_task(
                    Session(
                        browser_factory=lambda: browser,
                        agent=agent,
                        verification=verification,
                    ).run(prepared)
                )
                await asyncio.wait_for(active.wait(), 2)
                await asyncio.wait_for(closed.wait(), 2)
                if cancel:
                    task.cancel()
                    with self.assertRaises(SessionCancelled) as cancellation:
                        await task
                    result = cancellation.exception.result
                    self.assertEqual(result.errors, [])
                else:
                    result = await asyncio.wait_for(task, 2)
                    self.assertEqual(
                        [error.code for error in result.errors], ["deadline_exhausted"]
                    )
                self.assertEqual(result.stop_reason, "execution_completed")
                self.assertEqual(result.execution_outcome, ExecutionOutcome("Done"))
                self.assertTrue(released.is_set())
                self.assertEqual(len(deadlines), 3)
                self.assertEqual(len(set(deadlines)), 1)
                self.assertEqual(
                    [item.state for item in result.checkpoints],
                    ["finished", "finished"],
                )
                self.assertEqual(
                    [
                        item.verdict.status if item.verdict else None
                        for item in result.checkpoints
                    ],
                    ["error", "error"],
                )
                verification.evaluate.assert_awaited_once()

    async def test_cancelling_during_input_read_does_not_start_a_session(self):
        import threading
        from unittest.mock import patch

        entered = threading.Event()
        release = threading.Event()
        returned = threading.Event()
        original_read = Path.read_text
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "case.json")
            source.write_text(json.dumps(case()))

            def read_text(path, *args, **kwargs):
                if path == source:
                    entered.set()
                    release.wait(2)
                    returned.set()
                return original_read(path, *args, **kwargs)

            factory = Mock()
            browser_factory = Mock()
            with patch.object(Path, "read_text", read_text):
                task = asyncio.create_task(
                    SuiteRunner(factory, browser_factory=browser_factory).run(
                        source, {"defaults": config(directory)}
                    )
                )
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 1)
                    factory.assert_not_called()
                    browser_factory.assert_not_called()
                    self.assertEqual(list(Path(directory).iterdir()), [source])
                finally:
                    release.set()
                    self.assertTrue(await asyncio.to_thread(returned.wait, 2))

    async def test_time_spent_saving_request_cannot_start_model_after_deadline(self):
        import time
        from unittest.mock import patch

        from agent_support import finish_execution
        from input_fixtures import prepared_case
        from pydantic_ai.models.function import FunctionModel

        from uiprobe.agent import ExecutionAgent
        from uiprobe.observation import BrowserState, Screenshot
        from uiprobe.recording import SessionRecord, SubmissionRecord
        from uiprobe.session import Session
        from uiprobe.verification import Verification

        for target in (SessionRecord, SubmissionRecord):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory() as directory,
            ):
                deadline = 0.0
                browser = AsyncMock()

                async def open_browser(entry_url, data_values, deadline_at):
                    nonlocal deadline
                    deadline = deadline_at
                    return BrowserState(Screenshot("screen-1", b"png", 1, 1), 1, 1)

                def save_request(record, *args):
                    original_save(record, *args)
                    time.sleep(
                        max(0, deadline - asyncio.get_running_loop().time()) + 0.01
                    )

                browser.open.side_effect = open_browser
                execution = Mock(
                    side_effect=lambda messages, info: finish_execution(info)
                )
                verification = Mock()
                defaults = config(directory)
                defaults["timeout_seconds"] = 0.35
                original_save = target.save_sent_messages
                with patch.object(target, "save_sent_messages", save_request):
                    result = await Session(
                        browser_factory=lambda: browser,
                        agent=ExecutionAgent(FunctionModel(execution)),
                        verification=Verification(FunctionModel(verification)),
                    ).run(prepared_case(defaults))

                self.assertEqual(result.status, "error")
                self.assertEqual(
                    [error.code for error in result.errors], ["deadline_exhausted"]
                )
                verification.assert_not_called()
                if target is SessionRecord:
                    execution.assert_not_called()
                else:
                    self.assertEqual(result.checkpoints[0].state, "finished")

    async def test_browser_close_wait_is_bounded_even_if_cancellation_starts_cleanup(
        self,
    ):
        from unittest.mock import patch

        from agent_support import submit_and_finish
        from input_fixtures import prepared_case

        from uiprobe.observation import BrowserState, Screenshot, Verdict
        from uiprobe.session import Session

        closing_cancelled = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()
        browser = AsyncMock()
        browser.open.return_value = BrowserState(
            Screenshot("screen-1", b"png", 1, 1), 1, 1
        )

        async def close():
            try:
                await asyncio.Future()
            finally:
                closing_cancelled.set()
                await release.wait()
                closed.set()

        browser.close.side_effect = close
        agent = AsyncMock()
        agent.execute.side_effect = submit_and_finish
        verification = AsyncMock()
        verification.evaluate.return_value = Verdict("test-submission", "passed", [])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("uiprobe.session.FINALIZATION_SECONDS", 0.2),
        ):
            try:
                async with asyncio.timeout(1):
                    result = await Session(
                        browser_factory=lambda: browser,
                        agent=agent,
                        verification=verification,
                    ).run(prepared_case(config(directory)))
                self.assertTrue(closing_cancelled.is_set())
                self.assertFalse(closed.is_set())
                self.assertEqual(
                    [error.operation for error in result.errors], ["close_browser"]
                )
                verdict = result.checkpoints[0].verdict
                assert verdict is not None
                self.assertEqual(verdict.status, "passed")
            finally:
                release.set()
                await asyncio.wait_for(closed.wait(), 1)
