from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class LedgerChanged:
    store_id: int
    record_id: int
    record_date: date
    operation: Literal["created", "updated", "deleted"]
    actor_id: int
