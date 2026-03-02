from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def get_tz(tz_name: str):
    if tz_name.upper() == "UTC":
        return UTC
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo not available; use UTC")
    return ZoneInfo(tz_name)


def tz_label(tz) -> str:
    # Prefer IANA key when available
    key = getattr(tz, "key", None)
    if key:
        return str(key)

    # Fallback: UTC±HH:MM
    now = datetime.now(UTC)
    off = tz.utcoffset(now) or timedelta(0)
    total_min = int(off.total_seconds() // 60)
    sign = "+" if total_min >= 0 else "-"
    total_min = abs(total_min)
    hh = total_min // 60
    mm = total_min % 60
    return f"UTC{sign}{hh:02d}:{mm:02d}"


def parse_canvas_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def fmt_canvas_dt(value: str | None, tz) -> str:
    dt = parse_canvas_dt(value)
    if not dt:
        return ""
    return dt.astimezone(tz).replace(microsecond=0).isoformat()
