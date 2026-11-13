# AGENTS.md

## Project

UIProbe is a screenshot-driven single-case browser testing agent. It accepts test JSON and run configuration, operates a browser, performs independent visual verification, and saves run artifacts.

Tech stack: Python 3.11+, uv, Playwright, Pydantic AI, and the OpenAI Python SDK. Dependency versions are defined in `pyproject.toml` and `uv.lock`.

Keep this file limited to repository-wide instructions for coding agents. Architecture, interfaces, environment setup, and implementation details belong in project documentation.

## Documentation

Before changing code, read the system architecture, then use the module index to select the documents relevant to the task:

- Architecture and ownership boundaries: [system architecture](docs/design/system-architecture.md)
- Shared data and state semantics: [shared contracts](docs/design/contracts.md)
- Module interfaces, ownership, and error behavior: [module index](docs/design/modules/README.md)
- Environment setup and current usage: [README](README.md)

Design documents describe the target architecture; they do not imply that every interface or feature has been implemented. Check the code, tests, and the relevant plan's `progress.md` for implementation status.

Architecture and shared contracts constrain module implementations; execution plans follow the adopted design. Identify conflicts explicitly and update the owning design documents before implementing a design change. Discussion notes, prototypes, and demo cases become constraints only after adoption into the formal design.

## Execution Plans

Before working on the MVP, read the related plan package:

- Scope and acceptance criteria: [plan](docs/exec-plans/uiprobe-mvp/plan.md)
- Implementation batches and validation: [execution](docs/exec-plans/uiprobe-mvp/execution.md)
- Decisions and unresolved questions: [decisions](docs/exec-plans/uiprobe-mvp/decisions.md)
- Current status and validation evidence: [progress](docs/exec-plans/uiprobe-mvp/progress.md)

Select an unfinished batch whose dependencies are complete. After completing a batch, update progress, validation evidence, and relevant decisions. Update the owning design documents when interfaces or behavior change.

For cross-module features, lifecycle changes, or persistence changes, create or revise an execution plan before implementation. Define scope, dependencies, and observable acceptance criteria. Local fixes may proceed directly when no plan is needed.

## Validation

Use `uv` for project commands. Existing tests use `unittest`; ordinary regression tests do not require real model credentials.

```bash
# Format Python code and sort imports
uv run ruff check --select I --fix .
uv run ruff format .

# Static checks
uv run ruff check .
uv run ruff format --check .
uv run pyright

# Run a targeted test file; choose the file relevant to the change
uv run python -m unittest discover -s tests -p 'test_session_input.py' -v

# Run all existing tests
uv run python -m unittest discover -s tests -v
```

Run Ruff on changed Python files during development. Run all static checks before completing Python changes. Run relevant tests during development. Run the full suite before completing cross-module behavior changes or changes to shared contracts, lifecycle, or persistence.

Tests should exercise observable production behavior. Use controlled model responses for model-dependent tests and real local pages for browser behavior where required by the plan. Record real-model demonstrations separately; simulated results do not establish real-model acceptance.

Confirm that each command discovers and runs the expected tests. Fix validation failures rather than weakening checks. Report the checks performed and their results, and explain any checks that could not run.
