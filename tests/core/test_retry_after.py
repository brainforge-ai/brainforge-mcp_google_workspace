"""
Unit tests for the quota-aware 429/503 handling in core/utils.py (PLT-2298).
"""

import asyncio
import sys
import os

import httplib2
import pytest
from googleapiclient.errors import HttpError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.utils import (
    _retry_after_seconds,
    handle_http_errors,
    MAX_RETRY_DELAY,
)


def _resp(status, headers=None):
    r = httplib2.Response({"status": status})
    if headers:
        r.update(headers)
    return r


def test_retry_after_seconds_parses_number():
    err = HttpError(_resp(429, {"retry-after": "7"}), b"")
    assert _retry_after_seconds(err) == 7.0


def test_retry_after_seconds_missing_returns_none():
    assert _retry_after_seconds(HttpError(_resp(429), b"")) is None


def test_retry_after_seconds_http_date_returns_none():
    err = HttpError(_resp(429, {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}), b"")
    assert _retry_after_seconds(err) is None


def test_retry_after_seconds_non_finite_returns_none():
    assert _retry_after_seconds(HttpError(_resp(429, {"retry-after": "inf"}), b"")) is None


def test_retry_after_seconds_no_resp_returns_none():
    class _Bare:
        resp = None

    assert _retry_after_seconds(_Bare()) is None


@pytest.mark.asyncio
async def test_readonly_429_retries_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls = {"n": 0}

    @handle_http_errors("t", is_read_only=True, service_type="sheets")
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise HttpError(_resp(429, {"retry-after": "2"}), b"quota")
        return "ok"

    assert await fn() == "ok"
    assert calls["n"] == 3
    assert sleeps == [2.0, 2.0]


@pytest.mark.asyncio
async def test_large_retry_after_is_clamped(monkeypatch):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls = {"n": 0}

    @handle_http_errors("t", is_read_only=True, service_type="sheets")
    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise HttpError(_resp(429, {"retry-after": "9999"}), b"")
        return "ok"

    assert await fn() == "ok"
    assert sleeps == [float(MAX_RETRY_DELAY)]


@pytest.mark.asyncio
async def test_write_429_raises_without_retry(monkeypatch):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls = {"n": 0}

    @handle_http_errors("t", service_type="sheets")  # is_read_only defaults False
    async def fn():
        calls["n"] += 1
        raise HttpError(_resp(429), b"quota")

    with pytest.raises(Exception) as exc:
        await fn()
    assert calls["n"] == 1
    assert sleeps == []
    assert "429" in str(exc.value)


@pytest.mark.asyncio
async def test_non_sheets_message_omits_sheets_limits():
    @handle_http_errors("t", service_type="gmail")
    async def fn():
        raise HttpError(_resp(429), b"quota")

    with pytest.raises(Exception) as exc:
        await fn()
    assert "Sheets limits" not in str(exc.value)
