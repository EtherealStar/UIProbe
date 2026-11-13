"""Values shared by browser observations, submission and verification."""

from dataclasses import dataclass
from typing import Literal

Status = Literal["passed", "failed", "error"]


@dataclass(frozen=True)
class Screenshot:
    screenshot_id: str
    png: bytes
    image_width: int
    image_height: int


@dataclass(frozen=True)
class BrowserState:
    screenshot: Screenshot
    viewport_width: int
    viewport_height: int


@dataclass(frozen=True)
class Submission:
    text: str


@dataclass(frozen=True)
class AssertionResult:
    assertion_id: str
    status: Status
    reason: str
    screenshot_id: str | None


@dataclass(frozen=True)
class Verdict:
    status: Status
    assertions: list[AssertionResult]
