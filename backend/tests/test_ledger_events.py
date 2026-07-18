from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from app.events.ledger import LedgerChanged


def test_ledger_changed_is_an_immutable_write_event() -> None:
    event = LedgerChanged(
        store_id=11,
        record_id=22,
        record_date=date(2026, 7, 15),
        operation="updated",
        actor_id=33,
        row_version=4,
    )

    assert event.store_id == 11
    assert event.record_id == 22
    assert event.record_date == date(2026, 7, 15)
    assert event.operation == "updated"
    assert event.actor_id == 33
    assert event.row_version == 4

    with pytest.raises(FrozenInstanceError):
        event.row_version = 5  # type: ignore[misc]
