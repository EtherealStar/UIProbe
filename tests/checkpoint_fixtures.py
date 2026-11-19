import asyncio
import functools
import http.server
import json
import threading
from pathlib import Path

from agent_support import calls
from input_fixtures import case, config
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    UserPromptPart,
)

from uiprobe.case_input import prepare_suite


def prepare(test, directory, *identifiers, **settings):
    page = Path(directory, "page.html")
    page.write_text(
        '<button style="position:absolute;left:10px;top:10px" onclick="this.textContent=\'Clicked\'">Click me</button>'
    )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addAsyncCleanup(asyncio.to_thread, server.shutdown)
    defaults = {
        **config(directory),
        "entry_url": f"http://127.0.0.1:{server.server_port}/page.html",
        **settings,
    }
    test_case = case()
    test_case["checkpoints"] = [
        {
            "id": identifier,
            "execution": {"goal": f"Goal for {identifier}", "instructions": []},
            "assertions": [
                {"id": identifier, "expected": f"Evidence for {identifier}"}
            ],
        }
        for identifier in identifiers
    ]
    prepared = (
        prepare_suite(json.dumps(test_case), {"defaults": defaults}).entries[0].prepared
    )
    assert prepared is not None
    return prepared


def submit(identifier):
    return "submit_checkpoint", {"checkpoint_id": identifier}


def judge(identifier, status="passed"):
    return calls(
        (
            "final_result",
            {
                "results": [
                    {
                        "assertion_id": identifier,
                        "status": status,
                        "reason": "Observed evidence",
                    }
                ]
            },
        )
    )


def images(messages):
    return [
        item.data
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, list)
        for item in part.content
        if isinstance(item, BinaryContent)
    ]
