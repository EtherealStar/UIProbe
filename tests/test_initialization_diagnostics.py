import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_session_input import case, config

from uiprobe.browser import Browser
from uiprobe.session import Session


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_navigation_failure_is_located_and_browser_closed(self):
        with socket.socket() as reserved, tempfile.TemporaryDirectory() as directory:
            reserved.bind(("127.0.0.1", 0))
            cfg = config(directory)
            cfg["entry_url"] = f"http://127.0.0.1:{reserved.getsockname()[1]}/"
            browser = Browser()
            agent = AsyncMock()
            result = await Session(browser_factory=lambda: browser, agent=agent).run(
                json.dumps(case()), cfg
            )
            error = result.errors[0]
            self.assertEqual(error.operation, "navigate")
            self.assertEqual(error.phase, "initialization")
            diagnostic = json.loads(
                (
                    Path(directory)
                    / result.session_id
                    / "diagnostics"
                    / f"{error.error_id}.json"
                ).read_text()
            )
            self.assertIn("ERR_CONNECTION_REFUSED", diagnostic["traceback"])
            self.assertEqual(diagnostic["error_id"], error.error_id)
            agent.execute.assert_not_awaited()
            assert browser.browser is not None
            self.assertFalse(browser.browser.is_connected())

    async def test_oserror_from_browser_is_not_a_recording_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            try:
                try:
                    raise ConnectionError("socket root cause")
                except ConnectionError as cause:
                    raise OSError("browser wrapper") from cause
            except OSError as exc:
                browser.open.side_effect = exc
            result = await Session(browser_factory=lambda: browser).run(
                json.dumps(case()), config(directory)
            )
            error = result.errors[0]
            self.assertEqual(error.phase, "initialization")
            diagnostic = json.loads(
                (
                    Path(directory)
                    / result.session_id
                    / "diagnostics"
                    / f"{error.error_id}.json"
                ).read_text()
            )
            self.assertIn("socket root cause", diagnostic["traceback"])
            self.assertIn("browser wrapper", diagnostic["traceback"])
            browser.close.assert_awaited_once()

    async def test_startup_file_failure_uses_available_config_directory(self):
        from uiprobe.__main__ import run_files

        with tempfile.TemporaryDirectory() as directory:
            cfg_path = Path(directory) / "config.json"
            cfg_path.write_text(json.dumps(config(directory)))
            result = await run_files(Path(directory) / "missing.json", cfg_path)
            error = result.errors[0]
            self.assertEqual(error.operation, "read_case")
            diagnostic_path = (
                Path(directory)
                / result.session_id
                / "diagnostics"
                / f"{error.error_id}.json"
            )
            self.assertIn("FileNotFoundError", diagnostic_path.read_text())
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))
            result = await run_files(
                Path(directory) / "missing.json",
                Path(directory) / "missing-config.json",
            )
            self.assertEqual(result.errors[0].operation, "read_config")
            self.assertEqual(result.artifact_paths, [])

    async def test_initialization_timeout_retains_current_operation(self):
        import asyncio

        class SlowBrowser(Browser):
            async def open(self, entry_url, data_values, deadline_at):
                self.initialization_operation = "navigate"
                await asyncio.sleep(1)
                raise TimeoutError

        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["timeout_seconds"] = 0.02
            result = await Session(browser_factory=SlowBrowser).run(
                json.dumps(case()), cfg
            )
            self.assertEqual(result.errors[0].operation, "navigate")
            self.assertEqual(result.errors[0].phase, "initialization")
