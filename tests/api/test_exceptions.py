"""Tests for typed domain exception hierarchy and error handler mapping."""

from __future__ import annotations

import pytest

from api.error_handler import _public_error_for_exception
from api.exceptions import (
    KbClientError,
    KbConflict,
    KbError,
    KbForbidden,
    KbNotFound,
    KbServiceUnavailable,
)


@pytest.mark.parametrize(
    ("cls", "expected_status"),
    [
        (KbError, 500),
        (KbClientError, 400),
        (KbNotFound, 404),
        (KbConflict, 409),
        (KbForbidden, 403),
        (KbServiceUnavailable, 503),
    ],
)
def test_exception_types_have_expected_status_code(
    cls: type[KbError], expected_status: int
) -> None:
    assert cls.status_code == expected_status
    err = cls("msg")
    assert err.status_code == expected_status


@pytest.mark.parametrize(
    ("cls", "message", "expected_status", "expected_code"),
    [
        (KbError, "server error", 500, "kb_error"),
        (KbClientError, "bad input", 400, "kb_client_error"),
        (KbNotFound, "not found", 404, "kb_not_found"),
        (KbConflict, "conflict", 409, "kb_conflict"),
        (KbForbidden, "forbidden", 403, "kb_forbidden"),
        (KbServiceUnavailable, "unavailable", 503, "kb_service_unavailable"),
    ],
)
def test_public_error_for_exception_maps_all_kb_error_subclasses(
    cls: type[KbError],
    message: str,
    expected_status: int,
    expected_code: str,
) -> None:
    status, code, msg = _public_error_for_exception(cls(message))
    assert status == expected_status
    assert code == expected_code
    assert msg == message


def test_kb_error_stores_message_and_detail() -> None:
    err = KbError("primary", detail="debug info")
    assert err.message == "primary"
    assert err.detail == "debug info"


def test_public_error_still_maps_value_error_to_400() -> None:
    status, code, msg = _public_error_for_exception(ValueError("nope"))
    assert status == 400
    assert code == "bad_request"
    assert msg == "Bad request"
