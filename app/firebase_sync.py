"""Deprecated v11/v12 SQL-to-Firestore mirror.

This module is retained only for compatibility with old imports and tests. v13 no
longer installs or uses this mirror: when DATABASE_BACKEND=firestore, Firestore is
the primary persistence backend through app.firestore_database.
"""

def install(session_class):
    return None

# Backwards-compatible serializer retained for older integrations and tests.
def _serial(value):
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
