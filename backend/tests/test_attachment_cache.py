"""Tests for session-scoped attachment byte caching.

Seed attachments live in Postgres and were re-fetched on every evaluation,
which dominated the runtime of a warm re-run. They are now cached by file_id
and fetched concurrently. User-uploaded attachments arrive inline as base64
and must keep working untouched — they have no file_id and never hit the
database.

These exercise the resolution logic directly (no HTTP, no database).
"""

import base64

import pytest

import main
from engine.pipeline import SessionState


async def _resolve(session, emails, fetcher, monkeypatch=None):
    """Call the real resolver from main.py with fetch_attachment_bytes stubbed."""
    import main
    main.fetch_attachment_bytes = fetcher          # restored by the fixture
    return await main.resolve_attachments(emails, session)


@pytest.fixture(autouse=True)
def _restore_fetcher():
    original = main.fetch_attachment_bytes
    yield
    main.fetch_attachment_bytes = original


@pytest.fixture
def calls():
    return []


@pytest.fixture
def fetcher(calls):
    async def _f(file_id):
        calls.append(file_id)
        return f"BYTES:{file_id}".encode()
    return _f


def _seed_email(eid, fid, name="doc.pdf"):
    return {"_id": eid, "attachments": [
        {"name": name, "attachment_index": 0, "file_id": fid, "file_data": None}]}


def _upload_email(eid, raw=b"%PDF-1.4 uploaded", name="mine.pdf"):
    return {"_id": eid, "attachments": [{
        "name": name, "attachment_index": 0, "file_id": None,
        "file_data": base64.b64encode(raw).decode()}]}


class TestSeedAttachments:
    async def test_first_run_fetches_then_second_run_does_not(self, fetcher, calls):
        s = SessionState("s1")
        emails = [_seed_email("e1", "f1"), _seed_email("e2", "f2")]

        first = await _resolve(s, emails, fetcher)
        assert len(first) == 2
        assert sorted(calls) == ["f1", "f2"]

        calls.clear()
        second = await _resolve(s, emails, fetcher)
        assert calls == []                       # the whole point
        assert [a["file_bytes"] for a in second] == [a["file_bytes"] for a in first]

    async def test_shared_file_id_fetched_once(self, fetcher, calls):
        s = SessionState("s2")
        emails = [_seed_email("e1", "same"), _seed_email("e2", "same")]
        out = await _resolve(s, emails, fetcher)
        assert calls == ["same"]
        assert len(out) == 2                     # both emails still get bytes

    async def test_missing_bytes_skips_attachment_and_is_not_cached(self):
        s = SessionState("s3")

        async def none_fetcher(file_id):
            return None

        out = await _resolve(s, [_seed_email("e1", "gone")], none_fetcher)
        assert out == []
        assert "gone" not in s.attachment_cache   # a retry must be possible

    async def test_order_is_preserved(self, fetcher):
        s = SessionState("s4")
        emails = [_seed_email(f"e{i}", f"f{i}", f"doc{i}.pdf") for i in range(5)]
        out = await _resolve(s, emails, fetcher)
        assert [a["name"] for a in out] == [f"doc{i}.pdf" for i in range(5)]


class TestUserUploads:
    async def test_upload_resolves_without_any_fetch(self, fetcher, calls):
        s = SessionState("u1")
        out = await _resolve(s, [_upload_email("new_123")], fetcher)
        assert calls == []                        # never touches the database
        assert out[0]["file_bytes"] == b"%PDF-1.4 uploaded"
        assert s.attachment_cache == {}           # nothing to cache

    async def test_upload_alongside_seed_docs(self, fetcher, calls):
        s = SessionState("u2")
        emails = [_seed_email("e1", "f1"), _upload_email("new_9"), _seed_email("e2", "f2")]
        out = await _resolve(s, emails, fetcher)
        assert sorted(calls) == ["f1", "f2"]
        assert [a["email_id"] for a in out] == ["e1", "new_9", "e2"]
        assert out[1]["file_bytes"] == b"%PDF-1.4 uploaded"

    async def test_edited_upload_is_reread_not_cached(self, fetcher):
        """Replacing an uploaded PDF must take effect immediately."""
        s = SessionState("u3")
        first = await _resolve(s, [_upload_email("new_1", b"VERSION-ONE")], fetcher)
        assert first[0]["file_bytes"] == b"VERSION-ONE"
        second = await _resolve(s, [_upload_email("new_1", b"VERSION-TWO")], fetcher)
        assert second[0]["file_bytes"] == b"VERSION-TWO"

    async def test_corrupt_base64_is_skipped_not_fatal(self, fetcher):
        s = SessionState("u4")
        emails = [
            {"_id": "bad", "attachments": [{
                "name": "x.pdf", "attachment_index": 0,
                "file_id": None, "file_data": "!!!not base64!!!"}]},
            _seed_email("good", "f1"),
        ]
        out = await _resolve(s, emails, fetcher)
        assert [a["email_id"] for a in out] == ["good"]


class TestSessionIsolation:
    async def test_cache_does_not_leak_between_sessions(self, fetcher, calls):
        a, b = SessionState("a"), SessionState("b")
        await _resolve(a, [_seed_email("e1", "f1")], fetcher)
        calls.clear()
        await _resolve(b, [_seed_email("e1", "f1")], fetcher)
        assert calls == ["f1"]     # a page refresh re-fetches, as intended
