import asyncio
import unittest
from statistics import median
from time import process_time
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from starlette.requests import Request

from backend.store import AdmittedRun, Credential
from gateway.forwarder import _capture_failure_code, forward
from gateway.stream_capture import EventStreamDecoder

AsyncClient = httpx.AsyncClient


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    def test_capture_failure_categories(self):
        self.assertEqual(_capture_failure_code(OperationalError("write", {}, Exception())),
                         "capture_transient_error")
        self.assertEqual(_capture_failure_code(IntegrityError("write", {}, Exception())),
                         "capture_integrity_error")
        self.assertEqual(_capture_failure_code(ProgrammingError("write", {}, Exception())),
                         "capture_storage_error")

    async def test_knowledge_enabled_text_streams_before_upstream_finishes(self):
        release = asyncio.Event()

        class UpstreamStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'event: response.output_text.delta\ndata: {"delta":"Ola"}\n\n'
                await release.wait()
                yield b'event: response.completed\ndata: {"response":{"output":[],"usage":{"input_tokens":1}}}\n\n'

        async def unused_search(_query):
            self.fail("knowledge search was not requested")

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                               stream=UpstreamStream())
            )),
        ), patch("gateway.forwarder.append_events"), patch("gateway.forwarder.finish_transport"), patch(
            "backend.chat.materialize_artifact_request", return_value=None
        ):
            request = Request({"type": "http", "method": "POST", "path": "/api/chat/messages",
                               "query_string": b"", "headers": []})
            try:
                response = await asyncio.wait_for(forward(request, "responses", AdmittedRun(
                    uuid4(), Credential("c", "u", "personal_oauth", 60, 500)),
                    b'{"stream":true}', browser_session=True, knowledge_search=unused_search), 1)
                first = await asyncio.wait_for(anext(response.body_iterator), 1)
                self.assertIn(b"response.output_text.delta", first)
            finally:
                release.set()
            self.assertIn(b"response.completed", b"".join([part async for part in response.body_iterator]))

    def test_cr_delimited_terminal_event_is_complete_at_chunk_boundary(self):
        decoder = EventStreamDecoder()
        events = decoder.feed(b'event: response.completed\rdata: {"response": {}}\r\r')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "response.completed")
        self.assertEqual(events[0].data, '{"response": {}}')
        self.assertTrue(events[0].complete)

    def test_many_lf_delimited_events_in_one_chunk(self):
        decoder = EventStreamDecoder()
        events = decoder.feed(b"data: x\n\n" * 8000)
        self.assertEqual(len(events), 8000)
        self.assertEqual(events[-1].ordinal, 7999)
        self.assertTrue(all(event.data == "x" for event in events))

    def test_long_fragmented_line_scales_with_its_size(self):
        def decode(size):
            data = b"x" * size
            frame = b"event: response.completed\ndata: " + data + b"\n\n"
            decoder = EventStreamDecoder()
            events = []
            started = process_time()
            for offset in range(0, len(frame), 64):
                events.extend(decoder.feed(frame[offset:offset + 64]))
            events.extend(decoder.finish())
            elapsed = process_time() - started
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].data, data.decode())
            self.assertTrue(events[0].complete)
            return elapsed

        short = median(decode(256 * 1024) for _ in range(3))
        long = median(decode(512 * 1024) for _ in range(3))
        self.assertLess(long / short, 3.2)

    async def test_non_object_json_reaches_upstream(self):
        seen = []

        def upstream(request):
            seen.append(request.content)
            return httpx.Response(400, content=b"invalid payload")

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(upstream)),
        ), patch("gateway.forwarder.append_events"), patch("gateway.forwarder.finish_transport") as finish:
            request = Request({"type": "http", "method": "POST", "path": "/v1/responses", "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(uuid4(), Credential("c", "u", "personal_oauth", 60, 500)), b"[]")
            self.assertEqual(b"".join([part async for part in response.body_iterator]), b"invalid payload")

        self.assertEqual(seen, [b"[]"])
        finish.assert_called_once()

    async def test_stream_without_upstream_content_type_is_forwarded_and_captured(self):
        frame = b'event: response.completed\ndata: {"response": {"output": []}}\n\n'

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=frame)
            )),
        ), patch("gateway.forwarder.append_events") as capture, patch(
            "gateway.forwarder.finish_transport"
        ) as finish:
            request = Request({"type": "http", "method": "POST", "path": "/api/chat/messages",
                               "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(
                uuid4(), Credential("c", "u", "personal_oauth", 60, 500)),
                b'{"stream": true}', browser_session=True)
            self.assertEqual(response.headers["content-type"], "text/event-stream")
            self.assertEqual(b"".join([part async for part in response.body_iterator]), frame)

        self.assertEqual(capture.call_args.args[1][0].event_type, "response.completed")
        self.assertEqual(finish.call_args.args[2], "completed")

    async def test_knowledge_tool_keeps_both_turns_in_order(self):
        requests = []
        captured = []
        first = (b'event: response.output_item.added\ndata: {"item":{"type":"function_call"}}\n\n'
                 b'event: response.completed\ndata: {"response":{"output":[{"type":"function_call",'
                 b'"name":"search_department_knowledge","call_id":"call-1",'
                 b'"arguments":"{\\"query\\":\\"policy\\"}"}],"usage":{"input_tokens":2}}}\n\n')
        second = (b'event: response.output_text.delta\ndata: {"delta":"Found"}\n\n'
                  b'event: response.completed\ndata: {"response":{"output":[],"usage":{"input_tokens":3}}}\n\n')

        class Fragments(httpx.AsyncByteStream):
            def __init__(self, content):
                self.content = content

            async def __aiter__(self):
                for position in range(0, len(self.content), 7):
                    yield self.content[position:position + 7]

        def upstream(request):
            requests.append(request)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=Fragments(first if len(requests) == 1 else second))

        async def search(query):
            self.assertEqual(query, "policy")
            return {"output": "result", "sources": [{"name": "Policy"}]}

        async def capture(_run_id, events, _status):
            captured.extend(events)

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(upstream)),
        ), patch("gateway.forwarder.append_events", side_effect=capture), patch(
            "gateway.forwarder.finish_transport"
        ) as finish, patch("backend.chat.materialize_artifact_request", return_value=None), patch(
            "backend.chat.save_knowledge_sources", return_value=None
        ):
            request = Request({"type": "http", "method": "POST", "path": "/api/chat/messages",
                               "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(
                uuid4(), Credential("c", "u", "personal_oauth", 60, 500)),
                b'{"stream":true,"input":[],"tools":[{"name":"search_department_knowledge"}]}',
                browser_session=True, knowledge_search=search)
            body = b"".join([part async for part in response.body_iterator])

        self.assertEqual(body, first + second)
        self.assertEqual(len(requests), 2)
        self.assertEqual([event.ordinal for event in captured], list(range(len(captured))))
        self.assertEqual([event.event_type for event in captured], [
            "response.output_item.added", "response.completed", "maximus.knowledge_result",
            "response.output_text.delta", "response.completed",
        ])
        self.assertIn(b"function_call_output", requests[1].content)
        self.assertEqual(finish.call_args.args[2], "completed")

    async def test_client_cancellation_marks_run_interrupted(self):
        class WaitingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'event: response.output_text.delta\ndata: {"delta":"A"}\n\n'
                await asyncio.Event().wait()

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                               stream=WaitingStream()))),
        ), patch("gateway.forwarder.append_events"), patch(
            "gateway.forwarder.finish_transport"
        ) as finish, patch("backend.chat.materialize_artifact_request", return_value=None):
            request = Request({"type": "http", "method": "POST", "path": "/api/chat/messages",
                               "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(
                uuid4(), Credential("c", "u", "personal_oauth", 60, 500)),
                b'{"stream":true}', browser_session=True)
            self.assertIn(b"response.output_text.delta", await anext(response.body_iterator))
            await response.body_iterator.aclose()
        self.assertEqual(finish.call_args.args[2], "interrupted")

    async def test_upstream_stream_failure_marks_run_failed(self):
        class FailingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'event: response.output_text.delta\ndata: {"delta":"A"}\n\n'
                raise httpx.ReadError("upstream disconnected")

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                               stream=FailingStream()))),
        ), patch("gateway.forwarder.append_events"), patch(
            "gateway.forwarder.finish_transport"
        ) as finish, patch("backend.chat.materialize_artifact_request", return_value=None):
            request = Request({"type": "http", "method": "POST", "path": "/api/chat/messages",
                               "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(
                uuid4(), Credential("c", "u", "personal_oauth", 60, 500)),
                b'{"stream":true}', browser_session=True)
            with self.assertRaises(httpx.ReadError):
                b"".join([part async for part in response.body_iterator])
        self.assertEqual(finish.call_args.args[2:], ("failed", "upstream_stream_error"))

    async def test_query_string_reaches_upstream(self):
        seen = []

        def upstream(request):
            seen.append(str(request.url))
            return httpx.Response(200, content=b"ok")

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(upstream)),
        ), patch("gateway.forwarder.append_events"), patch("gateway.forwarder.finish_transport"):
            request = Request({
                "type": "http", "method": "GET", "path": "/v1/models",
                "query_string": b"limit=2&tag=a&tag=b", "headers": [],
            })
            response = await forward(request, "models", AdmittedRun(uuid4(), Credential("c", "u", "personal_oauth", 60, 500)), b"")
            self.assertEqual(b"".join([part async for part in response.body_iterator]), b"ok")

        self.assertEqual(seen, ["https://chatgpt.com/backend-api/codex/models?limit=2&tag=a&tag=b"])

    async def test_capture_failure_does_not_truncate_response(self):
        async def broken_capture(*args):
            raise RuntimeError("database unavailable")

        finishes = []

        async def finish(*args):
            finishes.append(args)

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"full response"))
            ),
        ), patch("gateway.forwarder.append_events", side_effect=broken_capture), patch(
            "gateway.forwarder.finish_transport", side_effect=finish
        ):
            request = Request({"type": "http", "method": "POST", "path": "/v1/responses", "query_string": b"", "headers": []})
            response = await forward(request, "responses", AdmittedRun(uuid4(), Credential("c", "u", "personal_oauth", 60, 500)), b"{}")
            self.assertEqual(b"".join([part async for part in response.body_iterator]), b"full response")

        self.assertEqual(finishes[0][2:], ("incomplete", "capture_error"))

    async def test_browser_proxy_does_not_forward_internal_headers(self):
        seen = []

        def upstream(request):
            seen.append(request.headers)
            return httpx.Response(200, content=b"ok", headers={"set-cookie": "upstream=secret"})

        with patch("gateway.forwarder.get_valid_token", return_value="oauth"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(upstream)),
        ), patch("gateway.forwarder.append_events"), patch("gateway.forwarder.finish_transport"):
            request = Request({
                "type": "http", "method": "POST", "path": "/api/credentials/c/v1/responses",
                "query_string": b"", "headers": [
                    (b"cookie", b"harness_session=secret"), (b"origin", b"https://app.test"),
                    (b"referer", b"https://app.test/chat"), (b"content-type", b"application/json"),
                ],
            })
            response = await forward(request, "responses", AdmittedRun(uuid4(), Credential(
                "c", "u", "shared_oauth", 60, 500)), b"{}", browser_session=True)
            self.assertEqual(b"".join([part async for part in response.body_iterator]), b"ok")
            self.assertNotIn("set-cookie", response.headers)

        self.assertEqual(seen[0]["authorization"], "Bearer oauth")
        self.assertEqual(seen[0]["content-type"], "application/json")
        self.assertNotIn("cookie", seen[0])
        self.assertNotIn("origin", seen[0])
        self.assertNotIn("referer", seen[0])


if __name__ == "__main__":
    unittest.main()
