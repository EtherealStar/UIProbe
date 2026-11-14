"""Single fixed viewport browser and raw observations."""

import asyncio
import struct
from collections.abc import Callable

from playwright.async_api import async_playwright

from .error_handling import locate
from .observability import fact, traced
from .observation import BrowserState, Screenshot


class BrowserRejected(Exception):
    """Correctable rejection before dispatch."""


class Browser:
    def __init__(
        self,
        *,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        device_scale_factor: float = 1,
    ):
        self.scale = device_scale_factor
        self.width = viewport_width
        self.height = viewport_height
        self.playwright = None
        self.browser = None
        self.page = None
        self.sequence = 0

    @traced("browser.open")
    async def open(
        self, entry_url: str, data_values: dict[str, str], deadline_at: float
    ) -> BrowserState:
        if asyncio.get_running_loop().time() >= deadline_at:
            raise TimeoutError
        self.data_values = dict(data_values)
        async with asyncio.timeout_at(deadline_at):
            self.initialization_operation = "launch_browser"
            with locate(
                "initialization",
                "launch_browser",
                "browser_start_failed",
                "Cannot start browser",
            ):
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless
                )
                self.context = await self.browser.new_context(
                    viewport={"width": self.width, "height": self.height},
                    device_scale_factor=self.scale,
                )
                self.page = await self.context.new_page()
            self.initialization_operation = "navigate"
            with locate(
                "initialization",
                "navigate",
                "navigation_failed",
                "Cannot navigate to entry URL",
            ):
                response = await self.page.goto(entry_url)
                fact(
                    "navigation",
                    url=self.page.url,
                    http_status=response.status if response else 0,
                )
            self.initialization_operation = "capture_initial"
            with locate(
                "initialization",
                "capture_initial",
                "capture_failed",
                "Cannot capture initial screenshot",
            ):
                return await self.capture(deadline_at)

    @traced("browser.capture")
    async def capture(self, deadline_at: float) -> BrowserState:
        assert self.page is not None
        if asyncio.get_running_loop().time() >= deadline_at:
            raise TimeoutError
        async with asyncio.timeout_at(deadline_at):
            if len(self.context.pages) != 1:
                raise RuntimeError("Multiple pages are unsupported")
            png = await self.page.screenshot(type="png", full_page=False)
            width, height = struct.unpack(">II", png[16:24])
            self.sequence += 1
            self.state = BrowserState(
                Screenshot(f"screen-{self.sequence}", png, width, height),
                self.width,
                self.height,
            )
            fact(
                "screenshot",
                screenshot_id=self.state.screenshot.screenshot_id,
                image_width=width,
                image_height=height,
                viewport_width=self.width,
                viewport_height=self.height,
            )
            return self.state

    async def click(
        self,
        screenshot_id: str,
        x: int,
        y: int,
        deadline_at: float,
        before_dispatch: Callable[[], object],
    ) -> dict:
        assert self.page is not None
        state = self.state
        if screenshot_id != state.screenshot.screenshot_id:
            raise BrowserRejected("Screenshot is stale")
        if (
            type(x) is not int
            or type(y) is not int
            or not (
                0 <= x < state.screenshot.image_width
                and 0 <= y < state.screenshot.image_height
            )
        ):
            raise BrowserRejected("Coordinates outside screenshot")
        css_x = x * state.viewport_width / state.screenshot.image_width
        css_y = y * state.viewport_height / state.screenshot.image_height
        async with asyncio.timeout_at(deadline_at):
            before_dispatch()
            await self.page.mouse.click(css_x, css_y)
        return {"css_x": css_x, "css_y": css_y}

    async def fill_value(
        self, ref: str, deadline_at: float, before_dispatch: Callable[[], object]
    ) -> dict:
        assert self.page is not None
        if not ref.strip() or ref not in self.data_values:
            raise BrowserRejected("Unknown data reference")
        async with asyncio.timeout_at(deadline_at):
            editable = await self.page.evaluate("""() => {
                const e = document.activeElement;
                return !!e && !e.disabled && !e.readOnly &&
                    (e.isContentEditable || e.tagName === 'TEXTAREA' ||
                     (e.tagName === 'INPUT' && ['text','password','email','search','tel','url','number'].includes(e.type)));
            }""")
            if not editable:
                raise BrowserRejected("Focused element is not editable")
            before_dispatch()
            await self.page.locator(":focus").fill(self.data_values[ref])
        return {"ref": ref}

    async def scroll(
        self, delta_y: int, deadline_at: float, before_dispatch: Callable[[], object]
    ) -> dict:
        assert self.page is not None
        if type(delta_y) is not int:
            raise BrowserRejected("Scroll requires integer CSS pixels")
        async with asyncio.timeout_at(deadline_at):
            before_dispatch()
            await self.page.evaluate("y => window.scrollBy(0, y)", delta_y)
        return {"delta_y": delta_y}

    async def wait(
        self,
        duration_ms: int,
        deadline_at: float,
        before_dispatch: Callable[[], object],
    ) -> dict:
        if type(duration_ms) is not int or not 0 < duration_ms <= 10000:
            raise BrowserRejected("Wait must be between 1 and 10000 milliseconds")
        if duration_ms / 1000 >= deadline_at - asyncio.get_running_loop().time():
            raise BrowserRejected("Wait exceeds remaining time")
        async with asyncio.timeout_at(deadline_at):
            before_dispatch()
            await asyncio.sleep(duration_ms / 1000)
        return {"duration_ms": duration_ms}

    @traced("browser.close")
    async def close(self) -> None:
        try:
            if self.browser is not None:
                await self.browser.close()
        finally:
            if self.playwright is not None:
                await self.playwright.stop()
