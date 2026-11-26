"""Time in the form the database stores it: UTC, ISO 8601 with milliseconds and Z (2026-11-11T08:30:00.000Z)."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
