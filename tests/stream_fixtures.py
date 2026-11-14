"""Controlled SSE responses with split text and tool arguments."""

import json

import httpx2


def streamed_completion(completion: dict) -> httpx2.Response:
    chunks = []
    base = {key: completion[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    for choice in completion["choices"]:
        message = choice["message"]
        deltas = [{"role": message["role"]}]
        content = message.get("content")
        if content:
            midpoint = len(content) // 2
            deltas.extend(
                {"content": part} for part in (content[:midpoint], content[midpoint:])
            )
        for index, call in enumerate(message.get("tool_calls", [])):
            function = call["function"]
            arguments = function["arguments"]
            midpoint = len(arguments) // 2
            deltas.append(
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": function["name"],
                                "arguments": arguments[:midpoint],
                            },
                        }
                    ]
                }
            )
            deltas.append(
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "function": {"arguments": arguments[midpoint:]},
                        }
                    ]
                }
            )
        for delta in deltas:
            chunks.append(
                {
                    **base,
                    "choices": [
                        {
                            "index": choice["index"],
                            "delta": delta,
                            "finish_reason": None,
                        }
                    ],
                }
            )
        chunks.append(
            {
                **base,
                "choices": [
                    {
                        "index": choice["index"],
                        "delta": {},
                        "finish_reason": choice["finish_reason"],
                    }
                ],
            }
        )
    if "usage" in completion:
        chunks.append({**base, "choices": [], "usage": completion["usage"]})
    content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=content + "data: [DONE]\n\n",
    )
