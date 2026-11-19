"""Strict input preparation independent of runtime resources."""

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
)


def _utf8(value: str) -> str:
    value.encode("utf-8")
    return value


Text = Annotated[str, AfterValidator(_utf8)]
_http_url = TypeAdapter(HttpUrl)


class StrictValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Execution(StrictValue):
    goal: Text
    instructions: list[Text]

    @field_validator("goal")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank text")
        return value


class Assertion(StrictValue):
    model_config = ConfigDict(frozen=True)

    id: Text
    expected: Text

    @field_validator("id", "expected")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return Execution.nonblank(value)


class Checkpoint(StrictValue):
    id: Text

    @field_validator("id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return Execution.nonblank(value)

    execution: Execution
    assertions: list[Assertion] = Field(min_length=1)


class TestCase(StrictValue):
    id: Text
    name: Text
    checkpoints: list[Checkpoint] = Field(min_length=1)

    @field_validator("id", "name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return Execution.nonblank(value)


class SessionConfig(StrictValue):
    entry_url: Text
    data_values: dict[Text, Text] = Field(repr=False)
    max_actions: int = Field(gt=0)
    execution_request_limit: int = Field(gt=0)
    verification_request_limit: int = Field(gt=0)
    tool_call_limit: int = Field(gt=0)
    tool_retry_limit: int = Field(gt=0)
    verification_retry_limit: int = Field(gt=0)
    verification_concurrency: int = Field(default=1, gt=0)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    output_dir: str

    @field_validator("entry_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError("invalid URL")
        try:
            _http_url.validate_python(value)
        except ValidationError:
            raise ValueError("invalid URL") from None
        return value

    @field_validator("output_dir")
    @classmethod
    def valid_directory(cls, value: str) -> str:
        if not value.strip() or chr(0) in value:
            raise ValueError("invalid directory")
        return _utf8(value)

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
    cause: OSError | None = field(default=None, repr=False)


@dataclass(frozen=True)
class SourceRef:
    source: str
    case_index: int


@dataclass(frozen=True)
class InputError:
    source: SourceRef | None
    errors: list[FieldError]


@dataclass(frozen=True)
class PreparedCase:
    test_case: TestCase
    session_config: SessionConfig = field(repr=False)
    source_ref: SourceRef


@dataclass(frozen=True)
class PreparedEntry:
    source: SourceRef
    case_id: str | None
    prepared: PreparedCase | None
    error: InputError | None


@dataclass(frozen=True)
class PreparedSuite:
    entries: list[PreparedEntry]
    errors: list[FieldError]
    output_dir: str | None


Value = TypeVar("Value", bound=BaseModel)


def _validate(
    model: type[Value], value: object, prefix: str, errors: list[FieldError]
) -> Value | None:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False):
            path = prefix
            location = error["loc"]
            if error["type"] == "extra_forbidden":
                location = location[:-1]
            for part in location:
                path += f"[{part}]" if isinstance(part, int) else f".{part}"
                if part == "data_values":
                    break
            errors.append(FieldError(path, error["type"]))
        return None


def _identifier(value: object) -> str | None:
    identifier = value.get("id") if isinstance(value, dict) else None
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    try:
        return _utf8(identifier)
    except UnicodeEncodeError:
        return None


def _duplicate_ids(items: list, path: str, errors: list[FieldError]) -> None:
    identifiers = [_identifier(item) for item in items]
    counts = Counter(identifiers)
    errors.extend(
        FieldError(f"{path}[{index}].id", "duplicate_id")
        for index, identifier in enumerate(identifiers)
        if identifier is not None and counts[identifier] > 1
    )


def _read_cases(source: str | Path, errors: list[FieldError]) -> list:
    try:
        raw = json.loads(
            source.read_text(encoding="utf-8") if isinstance(source, Path) else source
        )
    except OSError as exc:
        errors.append(FieldError("source", "unreadable_source", exc))
        return []
    except (ValueError, TypeError, RecursionError):
        errors.append(FieldError("source", "invalid_json_source"))
        return []
    if isinstance(raw, dict):
        if "cases" not in raw:
            return [raw]
        if len(raw) == 1 and isinstance(raw["cases"], list) and raw["cases"]:
            return raw["cases"]
    errors.append(FieldError("source", "invalid_suite_shape"))
    return []


def _read_config(
    config: object, errors: list[FieldError]
) -> tuple[SessionConfig | None, dict, str | None]:
    if isinstance(config, Path):
        try:
            config = json.loads(config.read_text(encoding="utf-8"))
        except OSError as exc:
            errors.append(FieldError("config", "unreadable_source", exc))
            return None, {}, None
        except (ValueError, RecursionError):
            errors.append(FieldError("config", "invalid_json_source"))
            return None, {}, None
    if not isinstance(config, dict):
        errors.append(FieldError("config", "invalid_configuration"))
        return None, {}, None
    if config.keys() - {"defaults", "case_overrides"}:
        errors.append(FieldError("config", "extra_forbidden"))
    overrides = config.get("case_overrides", {})
    if not isinstance(overrides, dict) or any(
        not isinstance(key, str) for key in overrides
    ):
        errors.append(FieldError("config.case_overrides", "invalid_override_mapping"))
        overrides = {}
    raw_defaults = config.get("defaults")
    defaults = _validate(SessionConfig, raw_defaults, "config.defaults", errors)
    output_dir = None
    if isinstance(raw_defaults, dict) and isinstance(
        raw_defaults.get("output_dir"), str
    ):
        try:
            output_dir = SessionConfig.valid_directory(raw_defaults["output_dir"])
        except ValueError:
            pass
    return defaults, overrides, output_dir


def _effective_config(
    defaults: SessionConfig, override: object, errors: list[FieldError]
) -> SessionConfig | None:
    path = "config.case_overrides"
    if not isinstance(override, dict):
        errors.append(FieldError(path, "invalid_override"))
        return None
    if override.keys() - {"entry_url", "data_values"}:
        errors.append(FieldError(path, "extra_forbidden"))
    effective = defaults.model_dump()
    if "entry_url" in override:
        effective["entry_url"] = override["entry_url"]
    if "data_values" in override:
        values = override["data_values"]
        effective["data_values"] = (
            {**defaults.data_values, **values} if isinstance(values, dict) else values
        )
    return _validate(SessionConfig, effective, path, errors)


def prepare_suite(source: str | Path, config: object) -> PreparedSuite:
    errors: list[FieldError] = []
    cases = _read_cases(source, errors)
    source_valid = not errors
    defaults, overrides, output_dir = _read_config(config, errors)
    counts = Counter(_identifier(value) for value in cases)
    if source_valid and overrides.keys() - counts.keys():
        errors.append(FieldError("config.case_overrides", "unmatched_case_id"))
    entries = []
    for index, value in enumerate(cases):
        ref = SourceRef(
            str(source) if isinstance(source, Path) else "inline JSON", index
        )
        case_id = _identifier(value)
        problems: list[FieldError] = []
        path = f"cases[{index}]"
        case = _validate(TestCase, value, path, problems)
        if case_id is not None and counts[case_id] > 1:
            problems.append(FieldError(f"{path}.id", "duplicate_id"))
        checkpoints = value.get("checkpoints") if isinstance(value, dict) else None
        if isinstance(checkpoints, list):
            _duplicate_ids(checkpoints, f"{path}.checkpoints", problems)
            for position, checkpoint in enumerate(checkpoints):
                assertions = (
                    checkpoint.get("assertions")
                    if isinstance(checkpoint, dict)
                    else None
                )
                if isinstance(assertions, list):
                    _duplicate_ids(
                        assertions,
                        f"{path}.checkpoints[{position}].assertions",
                        problems,
                    )
        effective = None
        if not errors and defaults is not None:
            effective = _effective_config(
                defaults, overrides.get(case_id, {}), problems
            )
        prepared = (
            PreparedCase(case, effective, ref)
            if case is not None and effective is not None and not problems
            else None
        )
        entries.append(
            PreparedEntry(
                ref, case_id, prepared, InputError(ref, problems) if problems else None
            )
        )
    return PreparedSuite(entries, errors, output_dir)
