from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class LedgerChanged:
    store_id: int
    record_id: int
    record_date: date
    operation: Literal["created", "updated", "deleted", "rolled_back"]
    actor_id: int
    row_version: int | None
