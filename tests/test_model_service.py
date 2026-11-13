import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from uiprobe.model_service import ModelService, ModelServiceConfig


def completion(message, finish_reason="stop"):
    return {
        "id": "completion-1",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ConfigTests(unittest.TestCase):
    def test_load_dotenv_without_modifying_environment(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {}, clear=True),
        ):
            path = Path(directory) / ".env"
            path.write_text(
                "OPENAI_BASE_URL=https://models.example/v1\n"
                "OPENAI_API_KEY='secret-${literal}'\n"
                "OPENAI_MODEL=test-model\n"
                "OPENAI_TIMEOUT=12.5\n"
            )
            config = ModelServiceConfig.from_env(path)
            self.assertEqual(config.base_url, "https://models.example/v1")
            self.assertEqual(config.api_key, "secret-${literal}")
            self.assertEqual(config.model, "test-model")
            self.assertEqual(config.timeout, 12.5)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn(config.api_key, repr(config))

    def test_environment_overrides_file(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"OPENAI_MODEL": "environment-model"}, clear=True),
        ):
            path = Path(directory) / ".env"
            path.write_text(
                "OPENAI_BASE_URL=https://models.example/v1\n"
                "OPENAI_API_KEY=secret\nOPENAI_MODEL=file-model\n"
            )
            config = ModelServiceConfig.from_env(path)
            self.assertEqual(config.model, "environment-model")
            self.assertEqual(config.timeout, 60)

    def test_missing_configuration_reports_field(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {}, clear=True),
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_BASE_URL is required"):
                ModelServiceConfig.from_env(Path(directory) / "missing.env")


class ModelServiceTests(unittest.IsolatedAsyncioTestCase):
    def service(self, handler):
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        with patch(
            "uiprobe.model_service.AsyncOpenAI",
            side_effect=lambda **kwargs: AsyncOpenAI(http_client=http_client, **kwargs),
        ):
            service = ModelService(
                ModelServiceConfig(
                    base_url="https://models.example/custom/v1",
                    api_key="test-key",
                    model="test-model",
                    timeout=30,
                )
            )
        self.addAsyncCleanup(service.close)
        return service

    async def test_text_request_and_full_sdk_response(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx2.Response(
                200, json=completion({"role": "assistant", "content": "收到"})
            )

        service = self.service(handler)
        messages: list[ChatCompletionMessageParam] = [
            {"role": "user", "content": "你好"}
        ]
        async with service:
            response = await service.complete(messages)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            str(requests[0].url), "https://models.example/custom/v1/chat/completions"
        )
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-key")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "model": "test-model",
                "messages": messages,
                "stream": False,
            },
        )
        self.assertEqual(response.choices[0].message.content, "收到")
        self.assertEqual(response.choices[0].finish_reason, "stop")
        assert response.usage is not None
        self.assertEqual(response.usage.total_tokens, 15)
        self.assertTrue(service.client.is_closed())

    async def test_images_tools_and_invalid_arguments_pass_through(self):
        calls = [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "click", "arguments": "{invalid"},
            },
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "unknown", "arguments": '{"x":"1"}'},
            },
        ]
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx2.Response(
                200,
                json=completion(
                    {"role": "assistant", "content": None, "tool_calls": calls},
                    "tool_calls",
                ),
            )

        service = self.service(handler)
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "截图 f0"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                    },
                ],
            }
        ]
        tools: list[ChatCompletionToolUnionParam] = [
            {
                "type": "function",
                "function": {
                    "name": "click",
                    "description": "Click a point",
                    "parameters": {"type": "object"},
                },
            }
        ]
        response = await service.complete(messages, tools=tools)
        self.assertEqual(
            requests,
            [
                {
                    "model": "test-model",
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                }
            ],
        )
        tool_calls = response.choices[0].message.tool_calls
        assert tool_calls is not None
        self.assertEqual(
            [call.model_dump() for call in tool_calls],
            calls,
        )

    async def test_no_tool_call_is_a_response(self):
        service = self.service(
            lambda request: httpx2.Response(
                200, json=completion({"role": "assistant", "content": "完成"})
            )
        )
        response = await service.complete([{"role": "user", "content": "继续"}])
        self.assertIsNone(response.choices[0].message.tool_calls)
        self.assertEqual(response.choices[0].message.content, "完成")

    async def test_sdk_http_errors_propagate_without_retry(self):
        for status, error_type in [
            (401, AuthenticationError),
            (429, RateLimitError),
            (500, InternalServerError),
        ]:
            with self.subTest(status=status):
                requests = []

                def handler(request):
                    requests.append(request)
                    return httpx2.Response(
                        status,
                        json={
                            "error": {"message": "service error", "type": "test_error"}
                        },
                        headers={"x-request-id": "request-failed"},
                    )

                service = self.service(handler)
                with self.assertRaises(error_type) as raised:
                    await service.complete([{"role": "user", "content": "hello"}])
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.request_id, "request-failed")
                self.assertEqual(len(requests), 1)

    async def test_sdk_transport_errors_propagate_without_retry(self):
        for transport_error, sdk_error in [
            (httpx2.ReadTimeout, APITimeoutError),
            (httpx2.ConnectError, APIConnectionError),
        ]:
            with self.subTest(error=sdk_error):
                requests = []

                def handler(request):
                    requests.append(request)
                    raise transport_error("connection failed", request=request)

                service = self.service(handler)
                with self.assertRaises(sdk_error):
                    await service.complete([{"role": "user", "content": "hello"}])
                self.assertEqual(len(requests), 1)

    async def test_configured_timeout_and_override_reach_transport(self):
        timeouts = []

        def handler(request):
            timeouts.append(request.extensions["timeout"])
            return httpx2.Response(
                200, json=completion({"role": "assistant", "content": "ok"})
            )

        service = self.service(handler)
        await service.complete([{"role": "user", "content": "hello"}])
        await service.complete([{"role": "user", "content": "hello"}], timeout=0.5)
        self.assertTrue(all(value == 30 for value in timeouts[0].values()))
        self.assertTrue(all(value == 0.5 for value in timeouts[1].values()))


if __name__ == "__main__":
    unittest.main()
