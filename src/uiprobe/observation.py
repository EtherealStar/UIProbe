"""Values shared by browser observations, submission and verification."""

from dataclasses import dataclass
from typing import Literal

from .case_input import Assertion

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
class CheckpointSubmission:
    submission_id: str
    session_id: str
    checkpoint_id: str | None
    assertions: tuple[Assertion, ...]
    screenshot: Screenshot | None


@dataclass(frozen=True)
class AssertionResult:
    assertion_id: str
    status: Status
    reason: str
    screenshot_id: str | None


@dataclass(frozen=True)
class Verdict:
    submission_id: str
    status: Status
    assertions: list[AssertionResult]
