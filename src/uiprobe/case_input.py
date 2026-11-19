"""Strict input preparation independent of runtime resources."""

import json
import math
from dataclasses import dataclass, field
from typing import TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class StrictValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Execution(StrictValue):
    goal: str
    instructions: list[str]

    @field_validator("goal")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank text")
        return value


class Assertion(StrictValue):
    model_config = ConfigDict(frozen=True)

    id: str
    expected: str

    @field_validator("id", "expected")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return Execution.nonblank(value)


class TestCase(StrictValue):
    execution: Execution
    assertions: list[Assertion] = Field(min_length=1)


class SessionConfig(StrictValue):
    entry_url: str
    data_values: dict[str, str] = Field(repr=False)
    max_actions: int = Field(gt=0)
    execution_request_limit: int = Field(gt=0)
    verification_request_limit: int = Field(gt=0)
    tool_call_limit: int = Field(gt=0)
    tool_retry_limit: int = Field(gt=0)
    verification_retry_limit: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    output_dir: str

    @field_validator("entry_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("invalid URL")
        return value

    @field_validator("output_dir")
    @classmethod
    def valid_directory(cls, value: str) -> str:
        if not value.strip() or chr(0) in value:
            raise ValueError("invalid directory")
        return value

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def numeric_timeout(cls, value: object) -> object:
        if not isinstance(value, (float, int)) or type(value) not in (float, int):
            raise ValueError("invalid timeout")
        try:
            if not math.isfinite(value):
                raise ValueError("invalid timeout")
        except OverflowError:
            raise ValueError("invalid timeout") from None
        return value


@dataclass(frozen=True)
class FieldError:
    path: str
    reason: str


@dataclass(frozen=True)
class InputError:
    errors: list[FieldError]


@dataclass(frozen=True)
class PreparedSession:
    test_case: TestCase
    config: SessionConfig = field(repr=False)


Value = TypeVar("Value", bound=BaseModel)


def _validate(
    model: type[Value], value: object, prefix: str, errors: list[FieldError]
) -> Value | None:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False):
            path = prefix
            location = (
                error["loc"][:-1]
                if error["type"] == "extra_forbidden"
                else error["loc"]
            )
            for part in location:
                path += (
                    f"[{part}]"
                    if isinstance(part, int)
                    else ("." if path else "") + part
                )
            if path.startswith("config.data_values"):
                path = "config.data_values"
            errors.append(FieldError(path, error["type"]))
        return None


def prepare(test_json: str, config: object) -> PreparedSession | InputError:
    errors: list[FieldError] = []
    case = None
    try:
        raw = json.loads(test_json)
    except (ValueError, TypeError):
        errors.append(FieldError("test_json", "invalid_json"))
    else:
        case = _validate(TestCase, raw, "", errors)
        if isinstance(raw, dict) and isinstance(raw.get("assertions"), list):
            seen = set()
            for index, assertion in enumerate(raw["assertions"]):
                if isinstance(assertion, dict) and isinstance(assertion.get("id"), str):
                    identifier = assertion["id"]
                    if identifier in seen:
                        errors.append(
                            FieldError(f"assertions[{index}].id", "duplicate_id")
                        )
                    seen.add(identifier)
    parsed_config = _validate(SessionConfig, config, "config", errors)
    if errors:
        return InputError(errors)
    assert case is not None and parsed_config is not None
    return PreparedSession(case, parsed_config)
