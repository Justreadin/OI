from datetime import date, datetime, timezone
from decimal import Decimal

from app.firebase_sync import _serial


def test_firestore_serializer_handles_common_sql_values():
    assert _serial(date(2026, 11, 13)) == "2026-11-13"
    assert _serial(datetime(2026, 11, 13, tzinfo=timezone.utc)).startswith("2026-11-13T")
    assert _serial(Decimal("12.50")) == 12.5
    assert _serial("value") == "value"
    assert _serial(None) is None
