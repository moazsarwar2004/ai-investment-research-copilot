"""Structured logging schema and redaction-by-allowlist tests."""

from __future__ import annotations

import json
import logging

from backend.app.core.logger import JsonFormatter, bind_request_id, reset_request_id


def test_json_formatter_emits_schema_and_ignores_arbitrary_extra() -> None:
    formatter = JsonFormatter(service="test-service", environment="testing")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.status_code = 200
    record.authorization = "Bearer should-never-be-logged"
    token = bind_request_id("cf27a04c-4ac7-435e-938c-1358a57450bb")

    try:
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["event"] == "request_completed"
    assert payload["request_id"] == "cf27a04c-4ac7-435e-938c-1358a57450bb"
    assert payload["status_code"] == 200
    assert "authorization" not in payload
    assert "Bearer" not in json.dumps(payload)


def test_json_formatter_keeps_bounded_dependency_failure_context() -> None:
    formatter = JsonFormatter(service="test-service", environment="testing")
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="dependency_probe_failed",
        args=(),
        exc_info=None,
    )
    record.dependency = "database"
    record.exception_type = "ConnectionError"

    payload = json.loads(formatter.format(record))

    assert payload["dependency"] == "database"
    assert payload["exception_type"] == "ConnectionError"
