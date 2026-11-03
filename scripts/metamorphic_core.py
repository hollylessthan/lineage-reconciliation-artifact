"""Contract-conditioned metamorphic relations over ingestion histories.

Pure logic only: no catalog client imports. A history is a tuple of steps; the
native adapter executes each history in a fresh, isolated namespace and returns
the observed current lineage as a set of (upstream, downstream) logical names.

Relation kinds:
  counted          a violation is a candidate defect under the path's contract
  control          checks that a native explicit operation can reach the target
  characterization recorded behavior; never counted as a defect
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

Edge = Tuple[str, str]
State = FrozenSet[Edge]
Step = Tuple[str, ...]
History = Tuple[Step, ...]

REPLACE, ADDITIVE, UNDETERMINED = 'replace', 'additive', 'undetermined'
CONTRACTS = (REPLACE, ADDITIVE, UNDETERMINED)


def rev(name: str) -> Step:
    return ('rev', name)


def ol(name: str, pattern: str) -> Step:
    """One OpenLineage run of revision `name` delivered with an event pattern."""
    return ('ol', name, pattern)


CLEAR: Step = ('clear',)


def cut(name: str) -> Step:
    """Native delivery of revision `name`, interrupted before the target's lineage write."""
    return ('cut', name)


@dataclass(frozen=True)
class Relation:
    id: str
    family: str
    a: History
    b: History
    comparator: str  # 'eq' or 'additive_bound'
    counted_under: FrozenSet[str]
    kind: str = 'counted'
    note: str = ''
    bound_from: Tuple[History, ...] = field(default_factory=tuple)

    def applies(self, contract: str) -> bool:
        return contract in self.counted_under or self.kind != 'counted'


BATCH = 'batch'  # dbt manifests and SQL views: one complete run per step
OPENLINEAGE = 'openlineage'


def batch_relations(*, supports_omit: bool = False) -> List[Relation]:
    r = [
        Relation('MR1a', BATCH, (rev('r0'), rev('r1')), (rev('r1'),), 'eq', frozenset({REPLACE}),
                 note='replacement with a surviving dependency'),
        Relation('MR1b', BATCH, (rev('r0'), rev('empty')), (rev('empty'),), 'eq', frozenset({REPLACE}),
                 note='final-dependency withdrawal'),
        Relation('MR1c', BATCH, (rev('r1'), rev('r0')), (rev('r0'),), 'eq', frozenset({REPLACE}),
                 note='reverse replacement'),
        Relation('MR2a', BATCH, (rev('r1'), rev('r1')), (rev('r1'),), 'eq', frozenset({REPLACE, ADDITIVE, UNDETERMINED}),
                 note='idempotent retry'),
        Relation('MR2b', BATCH, (rev('r0'), rev('empty'), rev('empty')), (rev('r0'), rev('empty')), 'eq',
                 frozenset({REPLACE, ADDITIVE, UNDETERMINED}), note='idempotent empty retry'),
        Relation('MR3', BATCH, (rev('r0'), CLEAR), (rev('empty'),), 'eq', frozenset(), kind='control',
                 note='native explicit clear reaches the fresh empty state'),
        Relation('MR4a', BATCH, (rev('r0'), rev('r1')), (rev('r1'),), 'additive_bound', frozenset({ADDITIVE}),
                 bound_from=((rev('r0'),), (rev('r1'),)), note='additive bound'),
        Relation('MR4b', BATCH, (rev('r0'), rev('empty')), (rev('empty'),), 'additive_bound', frozenset({ADDITIVE}),
                 bound_from=((rev('r0'),), (rev('empty'),)), note='additive bound with empty'),
    ]
    if supports_omit:
        r.append(Relation('MR7', BATCH, (rev('r0'), rev('omit')), (rev('r0'), rev('empty')), 'eq', frozenset(),
                          kind='characterization', note='omitted model vs explicit empty declaration'))
    return r


def fault_relations() -> List[Relation]:
    return [Relation('MR5', BATCH, (rev('r0'), cut('r1'), rev('r1')), (rev('r0'), rev('r1')), 'eq',
                     frozenset({REPLACE, ADDITIVE, UNDETERMINED}), note='interrupted delivery then complete retry')]


def openlineage_relations() -> List[Relation]:
    full, single = 'full', 'single'
    return [
        Relation('MR1a', OPENLINEAGE, (ol('r0', full), ol('r1', full)), (ol('r1', full),), 'eq', frozenset({REPLACE}),
                 note='new run replaces inputs'),
        Relation('MR1b', OPENLINEAGE, (ol('r0', full), ol('empty', full)), (ol('empty', full),), 'eq',
                 frozenset({REPLACE}), note='new run declares no inputs'),
        Relation('MR1c', OPENLINEAGE, (ol('r1', full), ol('r0', full)), (ol('r0', full),), 'eq', frozenset({REPLACE}),
                 note='reverse replacement'),
        Relation('MR2a', OPENLINEAGE, (ol('r1', full), ol('r1', full)), (ol('r1', full),), 'eq',
                 frozenset({REPLACE, ADDITIVE, UNDETERMINED}), note='repeated identical run'),
        Relation('MR9a', OPENLINEAGE, (ol('r1', 'inputs_in_start'),), (ol('r1', single),), 'eq',
                 frozenset({REPLACE, ADDITIVE, UNDETERMINED}),
                 note='run accumulation: inputs only on START (OpenLineage run cycle)'),
        Relation('MR9c', OPENLINEAGE, (ol('r1', 'inputs_omitted_complete'),), (ol('r1', single),), 'eq',
                 frozenset({REPLACE, ADDITIVE, UNDETERMINED}),
                 note='run accumulation: COMPLETE omits inputs property entirely'),
        Relation('MR9b', OPENLINEAGE, (ol('r1', 'inputs_in_complete'),), (ol('r1', single),), 'eq',
                 frozenset({REPLACE, ADDITIVE, UNDETERMINED}),
                 note='run accumulation: START without datasets, COMPLETE with them'),
        Relation('MR5', OPENLINEAGE, (ol('r0', full), ol('r1', 'start_only'), ol('r1', full)),
                 (ol('r0', full), ol('r1', full)), 'eq', frozenset({REPLACE, ADDITIVE, UNDETERMINED}),
                 note='producer stopped after START, then a complete run'),
        Relation('MR5i', OPENLINEAGE, (ol('r0', full), ol('r1', 'start_only')), (ol('r0', full),), 'eq', frozenset(),
                 kind='characterization', note='visible state while a run is incomplete'),
        Relation('MR4a', OPENLINEAGE, (ol('r0', full), ol('r1', full)), (ol('r1', full),), 'additive_bound',
                 frozenset({ADDITIVE, UNDETERMINED}), bound_from=((ol('r0', full),), (ol('r1', full),)),
                 note='additive bound'),
    ]


CALIBRATION = {
    BATCH: [(rev('r1'),), (rev('r0'), rev('r1'))],
    OPENLINEAGE: [(ol('r1', 'full'),), (ol('r0', 'full'), ol('r1', 'full'))],
}


def compare(rel: Relation, a: State, b: State, bounds: Iterable[State] = ()) -> Dict:
    if rel.comparator == 'eq':
        ok = a == b
        return {'holds': ok, 'missing': sorted(b - a), 'extra': sorted(a - b)}
    if rel.comparator == 'additive_bound':
        bounds = list(bounds)
        union = frozenset().union(*bounds) if bounds else frozenset()
        lower_ok, upper_ok = b <= a, a <= union
        return {'holds': lower_ok and upper_ok, 'missing': sorted(b - a), 'extra': sorted(a - union)}
    raise ValueError(rel.comparator)


def verdict(rel: Relation, contract: str, cmp: Optional[Dict]) -> str:
    if cmp is None:
        return 'not_testable'
    if rel.kind == 'counted' and contract not in rel.counted_under:
        return 'not_applicable'
    if cmp['holds']:
        return 'holds'
    return {'counted': 'violation', 'control': 'control_failed', 'characterization': 'differs'}[rel.kind]


def evaluate(relations: List[Relation], contract: str,
             observe: Callable[[History], Optional[State]]) -> List[Dict]:
    """Evaluate relations with a memoizing observer. `observe` returns None when a
    history cannot be executed (e.g. a cut point is not reachable)."""
    cache: Dict[History, Optional[State]] = {}

    def get(h: History) -> Optional[State]:
        if h not in cache:
            cache[h] = observe(h)
        return cache[h]

    rows = []
    for rel in relations:
        if rel.kind == 'counted' and contract not in rel.counted_under:
            rows.append(row(rel, contract, None, None, None, 'not_applicable'))
            continue
        a, b = get(rel.a), get(rel.b)
        bounds = [get(h) for h in rel.bound_from]
        if a is None or b is None or any(x is None for x in bounds):
            rows.append(row(rel, contract, a, b, None, 'not_testable'))
            continue
        cmp = compare(rel, a, b, bounds)
        rows.append(row(rel, contract, a, b, cmp, verdict(rel, contract, cmp)))
    return rows


def calibrate(family: str, observe_fresh: Callable[[History], Optional[State]]) -> Dict:
    """Run each calibration history twice in separate namespaces (no memoization)."""
    trials = []
    for h in CALIBRATION[family]:
        first, second = observe_fresh(h), observe_fresh(h)
        trials.append({'history': fmt(h), 'first': edges(first), 'second': edges(second),
                       'agree': first is not None and first == second})
    alarms = sum(not t['agree'] for t in trials)
    return {'trials': trials, 'false_alarms': alarms, 'rate': alarms / len(trials) if trials else None}


def fmt(h: History) -> List[str]:
    return [':'.join(s) for s in h]


def edges(s: Optional[State]):
    return None if s is None else sorted(list(e) for e in s)


def row(rel, contract, a, b, cmp, v):
    return {'relation': rel.id, 'kind': rel.kind, 'note': rel.note, 'contract': contract,
            'history_a': fmt(rel.a), 'history_b': fmt(rel.b), 'state_a': edges(a), 'state_b': edges(b),
            'comparison': cmp, 'verdict': v}


def summarize(rows: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r['verdict']] = out.get(r['verdict'], 0) + 1
    return out
