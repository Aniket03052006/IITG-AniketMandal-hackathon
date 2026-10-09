"""The simulated trade ledger of Module A: every approve or reject of a proposed rebalance, appended to a git-ignored JSONL file.

A decision is a record, not an order: nothing is sent anywhere, the served index never changes, and a stale proposal cannot be approved. Each line carries the hash of the line before it, so an
edited or removed line is detected (``chain_ok``), and a ledger whose chain is broken refuses new entries rather than extending a history it cannot vouch for.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import LABELS, VERSION, LedgerAction, LedgerEntry, LedgerView, PaperBook, RebalanceDecisions
from .weights import turnover

log = logging.getLogger("eventshock.rebalancer.ledger")
GENESIS = "0" * 64
MAX_RECORDS = 5000


class LedgerError(ValueError):
    """The ledger refuses the entry (broken chain, full, or an allocation that cannot be funded)."""


def entry_hash(prev_hash: str, entry: LedgerEntry) -> str:
    body = entry.model_dump(mode="json", exclude={"entry_hash", "stale"})
    return hashlib.sha256((prev_hash + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def approved_allocation(decisions: RebalanceDecisions, accepted: list[str] | None) -> tuple[list[float], list[str], list[str]]:
    """The allocation after accepting a subset of the proposal's trades: (weights in ``tickers`` order, accepted tickers, rejected tickers).

    Accepted trades are carried out in full unless buys and sells no longer balance, in which case the larger side is scaled down so that what is bought equals what is sold (a
    scaled trade stays between the old and the new weight, so the per-stock bounds hold; the caller still checks sector caps). Only accepting buys, or only sells, cannot be funded.
    """
    by = {d.ticker: d for d in decisions.decisions}
    unknown = sorted(set(accepted or []) - set(by))
    if unknown:
        raise LedgerError(f"not in the index: {', '.join(unknown)}")
    traded = {t for t, d in by.items() if d.side.value != "HOLD"}
    if accepted is None:   # approving all of it is approving the proposal exactly, including trades too small to be listed as a buy or a sell
        return [by[t].after for t in decisions.tickers], sorted(traded), []
    take = set(accepted) & traded
    buys = sum(by[t].trade for t in take if by[t].trade > 0)
    sells = sum(-by[t].trade for t in take if by[t].trade < 0)
    if (buys > 0) != (sells > 0):
        raise LedgerError("the accepted trades cannot be funded: the buys and the sells must both be accepted (a buy is paid for by a sell)")
    scale_buy = 1.0 if buys <= sells else sells / buys
    scale_sell = 1.0 if sells <= buys else buys / sells
    w = []
    for t in decisions.tickers:
        d = by[t]
        f = 0.0 if t not in take else (scale_buy if d.trade > 0 else scale_sell)
        w.append(d.before + f * d.trade)
    return w, sorted(take), sorted(traded - take)


class LedgerStore:
    def __init__(self, path: Path | None, *, max_records: int = MAX_RECORDS, clock: Callable[[], datetime] | None = None) -> None:
        self.path, self.max = path, max_records
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._items: list[LedgerEntry] = []
        self._broken_at: int | None = None
        if path is not None and path.is_file():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    self._items.append(LedgerEntry.model_validate_json(line))
                except ValueError as exc:
                    log.warning("ledger %s line %d unreadable: %s", path, n, str(exc).splitlines()[0])
                    self._broken_at = self._broken_at or n
        self._verify()

    # -------------------------------------------------------------------------------------------------------------------------------- chain
    def _verify(self) -> None:
        prev = GENESIS
        for i, e in enumerate(self._items):
            if e.seq != i + 1 or e.prev_hash != prev or entry_hash(prev, e) != e.entry_hash:
                self._broken_at = self._broken_at or e.seq
                return
            prev = e.entry_hash

    @property
    def chain_ok(self) -> bool:
        return self._broken_at is None

    @property
    def broken_at(self) -> int | None:
        return self._broken_at

    def __len__(self) -> int:
        return len(self._items)

    # -------------------------------------------------------------------------------------------------------------------------------- write
    def record(self, decisions: RebalanceDecisions, *, action: LedgerAction, approved: list[float], accepted: list[str], rejected: list[str], note: str, analyst: str,
               include_live: bool) -> LedgerEntry:
        with self._lock:
            if not self.chain_ok:
                raise LedgerError(f"the ledger's hash chain is broken at entry {self._broken_at}; new entries are refused until it is investigated")
            if len(self._items) >= self.max:
                raise LedgerError(f"the ledger holds at most {self.max} entries")
            by = {d.ticker: d for d in decisions.decisions}
            before = [by[t].before for t in decisions.tickers]
            proposed = [by[t].after for t in decisions.tickers]
            prev = self._items[-1].entry_hash if self._items else GENESIS
            gross = sum(abs(d.trade) for d in decisions.decisions)
            cost_rate = decisions.est_cost / gross if gross > 0 else 0.0   # the proposal's one-way cost per unit traded
            draft = LedgerEntry(
                id="lg_" + uuid.uuid4().hex[:12], seq=len(self._items) + 1, recorded_at=self._clock(), action=action, strategy=decisions.strategy, cycle_index=decisions.index,
                cycle_at=decisions.at, params=decisions.params, include_live=include_live, tickers=list(decisions.tickers), before=before, proposed=proposed, approved=approved,
                accepted_tickers=accepted, rejected_tickers=rejected, turnover=turnover(before, approved),
                est_cost=cost_rate * sum(abs(a - b) for a, b in zip(approved, before, strict=True)),
                tracking_difference=turnover(approved, proposed), proposal_sha256=decisions.proposal_sha256, analyst=analyst.strip(), note=note.strip(), prev_hash=prev, entry_hash="0" * 64)
            entry = draft.model_copy(update={"entry_hash": entry_hash(prev, draft)})
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(entry.model_dump_json(exclude={"stale"}) + "\n")
            self._items.append(entry)
            return entry

    # --------------------------------------------------------------------------------------------------------------------------------- read
    def all(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._items)

    def latest_for(self, strategy: str, cycle_index: int, params_key: tuple[float, float, float], include_live: bool) -> LedgerEntry | None:
        """The current decision on a proposal (the last recorded wins)."""
        with self._lock:
            for e in reversed(self._items):
                if (e.strategy, e.cycle_index, e.include_live) == (strategy, cycle_index, include_live) and (e.params.tilt, e.params.half_life_hours, e.params.max_turnover) == params_key:
                    return e
        return None


LEDGER_LABELS = [
    "A simulated ledger: approving a rebalance records a decision, it does not send an order, and the served index never changes.",
    "A decision is valid only for the exact proposal it was made on; if the strategy, parameters, cycle or evidence change, it is shown as stale.",
    *LABELS[:1],
]


def is_stale(svc, e: LedgerEntry) -> bool:  # noqa: ANN001
    """True when the proposal this entry was decided on is no longer the one the service would make (or no longer exists)."""
    try:
        return svc.decisions(e.cycle_index, e.params, e.include_live, e.strategy).proposal_sha256 != e.proposal_sha256
    except (LookupError, ValueError):
        return True


def view(store: LedgerStore, svc, *, limit: int = 200) -> LedgerView:  # noqa: ANN001
    items = store.all()
    newest = [e.model_copy(update={"stale": is_stale(svc, e)}) for e in reversed(items[-limit:])]
    approvals = [e for e in items if e.action is LedgerAction.APPROVE]
    book = None
    if approvals:
        last = approvals[-1]
        book = PaperBook(entry_id=last.id, cycle_at=last.cycle_at, strategy=last.strategy, tickers=last.tickers, weights=last.approved)
    return LedgerView(version=VERSION, chain_ok=store.chain_ok, broken_at=store.broken_at, entries=newest, total=len(items), approvals=len(approvals),
                      rejections=len(items) - len(approvals), paper_book=book, labels=LEDGER_LABELS)
