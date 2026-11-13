"""Single fixed viewport browser and raw observations."""

import asyncio
import struct

from playwright.async_api import async_playwright

from .observation import BrowserState, Screenshot


class Browser:
    def __init__(self, *, viewport_width: int = 1280, viewport_height: int = 720):
        self.width = viewport_width
        self.height = viewport_height
        self.playwright = None
        self.browser = None
        self.page = None
        self.sequence = 0

    async def open(
        self, entry_url: str, data_values: dict[str, str], deadline_at: float
    ) -> BrowserState:
        self.data_values = dict(data_values)
        async with asyncio.timeout_at(deadline_at):
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch()
            self.context = await self.browser.new_context(
                viewport={"width": self.width, "height": self.height}
            )
            self.page = await self.context.new_page()
            await self.page.goto(entry_url)
            return await self.capture(deadline_at)

    async def capture(self, deadline_at: float) -> BrowserState:
        assert self.page is not None
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
            return self.state

    async def close(self) -> None:
        try:
            if self.browser is not None:
                await self.browser.close()
        finally:
            if self.playwright is not None:
                await self.playwright.stop()
