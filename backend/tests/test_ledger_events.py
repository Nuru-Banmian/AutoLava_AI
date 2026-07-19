from dataclasses import FrozenInstanceError
from datetime import date
from typing import get_args, get_type_hints

import pytest

from app.events.ledger import LedgerChanged


def test_ledger_changed_is_an_immutable_write_event() -> None:
    event = LedgerChanged(
        store_id=11,
        record_id=22,
        record_date=date(2026, 7, 15),
        operation="updated",
        actor_id=33,
    )

    assert event.store_id == 11
    assert event.record_id == 22
    assert event.record_date == date(2026, 7, 15)
    assert event.operation == "updated"
    assert event.actor_id == 33
    assert set(get_type_hints(LedgerChanged)) == {
        "store_id",
        "record_id",
        "record_date",
        "operation",
        "actor_id",
    }
    assert get_args(get_type_hints(LedgerChanged)["operation"]) == (
        "created",
        "updated",
        "deleted",
    )

    with pytest.raises(FrozenInstanceError):
        event.actor_id = 5  # type: ignore[misc]
