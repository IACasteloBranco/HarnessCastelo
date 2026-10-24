import unittest
from statistics import median
from time import process_time
from unittest.mock import patch
from uuid import uuid4

import httpx
from starlette.requests import Request

from backend.store import AdmittedRun, Credential
from gateway.forwarder import forward
from gateway.stream_capture import EventStreamDecoder

AsyncClient = httpx.AsyncClient


class ProxyTests(unittest.IsolatedAsyncioTestCase):
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
