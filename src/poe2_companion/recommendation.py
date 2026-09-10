"""Bounded exhaustive slot plans; private items never enter public diagnostics."""
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations, product

from .engine_models import EngineError, EngineSlot, TradeChange
from .engine_protocol import WorkerChange


@dataclass(frozen=True)
class Option:
    change: WorkerChange
    public: TradeChange
    cost: Decimal


@dataclass(frozen=True)
class Plan:
    changes: list[WorkerChange]
    cost: Decimal
    public: list[TradeChange]


def enumerate_plans(pool: dict[EngineSlot, list[Option]], removable: set[EngineSlot],
                    max_changes: int, spend: Decimal) -> list[Plan]:
    choices = {slot: list(options) for slot, options in pool.items()}
    for slot in sorted(removable):
        choices.setdefault(slot, []).append(Option(WorkerChange(slot=slot, saved_item_id=0),
            TradeChange(slot=slot, action='unequip'), Decimal(0)))
    plans = [Plan([], Decimal(0), [])]  # Keep is implicit for unselected slots.
    for count in range(1, min(max_changes, len(choices)) + 1):
        for slots in combinations(sorted(choices), count):
            for options in product(*(choices[slot] for slot in slots)):
                refs = [o.public.listing_ref for o in options if o.public.action == 'equip']
                if len(set(refs)) != len(refs):
                    continue
                cost = sum((o.cost for o in options), Decimal(0))
                if cost > spend:
                    continue
                plans.append(Plan([o.change for o in options], cost, [o.public for o in options]))
                if len(plans) > 64:
                    # Ask the caller to narrow refs/removable slots; never prune silently.
                    raise EngineError('engine_candidate_space_too_large')
    return plans
