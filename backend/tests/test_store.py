import asyncio
import os
import time
import unittest
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select

from backend.database import Run, RunEvent, _session_factory, session_factory
from backend.store import (
    Credential, RequestRecord, StreamEvent, TokenBundle, admit, append_events,
    create_credential, finish_transport, issue_client_key, revoke_user, valid_access_token,
)


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires a disposable PostgreSQL database")
class TokenTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        _session_factory.cache_clear()

    async def test_expired_token_without_refresh_is_rejected(self):
        user = f"test-{uuid4().hex}"
        await create_credential(user, TokenBundle("old", None, time.time() - 1))
        credential = Credential(user, user, "personal_oauth", 60, 500)
        with self.assertRaises(PermissionError):
            await valid_access_token(credential, lambda tokens: None)

    async def test_refresh_does_not_block_admission_and_runs_once(self):
        user = f"test-{uuid4().hex}"
        await create_credential(user, TokenBundle("old", "refresh", time.time() - 1))
        key = await issue_client_key(user)
        credential = Credential(user, user, "personal_oauth", 60, 500)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def refresh(tokens):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return TokenBundle("new", "next", time.time() + 3600)

        first = asyncio.create_task(valid_access_token(credential, refresh))
        await asyncio.wait_for(started.wait(), 3)
        second = asyncio.create_task(valid_access_token(credential, refresh))
        try:
            admitted = await asyncio.wait_for(admit(key, RequestRecord("GET", "models", b"")), 2)
        finally:
            release.set()
        self.assertEqual(await asyncio.wait_for(first, 3), "new")
        self.assertEqual(await asyncio.wait_for(second, 3), "new")
        self.assertEqual(calls, 1)
        async with session_factory()() as session:
            self.assertIsNone(await session.scalar(select(Run.employee_id).where(Run.id == admitted.run_id)))

    async def test_revocation_during_refresh_prevents_token_update(self):
        user = f"test-{uuid4().hex}"
        await create_credential(user, TokenBundle("old", "refresh", time.time() - 1))
        credential = Credential(user, user, "personal_oauth", 60, 500)
        started = asyncio.Event()
        release = asyncio.Event()

        async def refresh(tokens):
            started.set()
            await release.wait()
            return TokenBundle("new", "next", time.time() + 3600)

        task = asyncio.create_task(valid_access_token(credential, refresh))
        await asyncio.wait_for(started.wait(), 3)
        await asyncio.wait_for(revoke_user(user), 2)
        release.set()
        with self.assertRaises(PermissionError):
            await asyncio.wait_for(task, 3)

    async def test_two_turn_usage_and_event_order(self):
        user = f"test-{uuid4().hex}"
        await create_credential(user, TokenBundle("test-token", None, time.time() + 3600))
        key = await issue_client_key(user)
        run_id = (await admit(key, RequestRecord("POST", "responses", b'{}'))).run_id
        await append_events(run_id, [StreamEvent(0, "response.completed",
            '{"response":{"output":[],"usage":{"input_tokens":2,"output_tokens":1}}}')], 200)
        await append_events(run_id, [StreamEvent(1, "maximus.knowledge_result", "{}"),
            StreamEvent(2, "response.completed",
            '{"response":{"output":[],"usage":{"input_tokens":3,"output_tokens":4}}}')], 200)
        await finish_transport(run_id, 200, "completed")
        async with session_factory()() as session:
            run = await session.get(Run, run_id)
            events = (await session.scalars(select(RunEvent).where(
                RunEvent.run_id == run_id).order_by(RunEvent.ordinal))).all()
        self.assertEqual(run.usage_json, {"input_tokens": 5, "output_tokens": 5})
        self.assertEqual(run.outcome, "completed")
        self.assertEqual([event.ordinal for event in events], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
