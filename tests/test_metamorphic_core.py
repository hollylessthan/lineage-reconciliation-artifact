import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import metamorphic_core as m  # noqa: E402

GRAPHS = {'r0': {('a', 'out'), ('b', 'out')}, 'r1': {('a', 'out'), ('c', 'out')}, 'empty': set(), 'omit': set()}


def simulate(policy):
    """Toy catalogs: replace, additive, and replace-but-skips-empty (the known boundary)."""
    def observe(history):
        state = set()
        for step in history:
            kind, name = step[0], step[1] if len(step) > 1 else None
            if kind == 'clear':
                state = set()
            elif kind == 'cut':
                return None
            else:
                new = GRAPHS[name]
                if policy == 'replace':
                    state = set(new)
                elif policy == 'additive':
                    state |= new
                elif policy == 'skip_empty':
                    if new:
                        state = set(new)
        return frozenset(state)
    return observe


class CoreTests(unittest.TestCase):
    def verdicts(self, policy, contract):
        rows = m.evaluate(m.batch_relations(), contract, simulate(policy))
        return {r['relation']: r['verdict'] for r in rows}

    def test_replace_catalog_satisfies_replace_contract(self):
        v = self.verdicts('replace', m.REPLACE)
        self.assertEqual(v['MR1a'], 'holds')
        self.assertEqual(v['MR1b'], 'holds')
        self.assertEqual(v['MR3'], 'holds')
        self.assertEqual(v['MR4a'], 'not_applicable')

    def test_skip_empty_violates_only_withdrawal(self):
        v = self.verdicts('skip_empty', m.REPLACE)
        self.assertEqual(v['MR1a'], 'holds')
        self.assertEqual(v['MR1b'], 'violation')
        self.assertEqual(v['MR2b'], 'holds')  # repeated empty keeps the same wrong state

    def test_additive_not_flagged_under_additive_contract(self):
        v = self.verdicts('additive', m.ADDITIVE)
        self.assertEqual(v['MR1a'], 'not_applicable')
        self.assertEqual(v['MR4a'], 'holds')
        self.assertEqual(v['MR2a'], 'holds')

    def test_additive_would_false_alarm_if_unconditioned(self):
        v = self.verdicts('additive', m.REPLACE)
        self.assertEqual(v['MR1a'], 'violation')

    def test_unreachable_cut_is_not_testable(self):
        rows = m.evaluate(m.fault_relations(), m.REPLACE, simulate('replace'))
        self.assertEqual(rows[0]['verdict'], 'not_testable')

    def test_memoization_runs_each_history_once(self):
        calls = []
        base = simulate('replace')
        def observe(h):
            calls.append(h)
            return base(h)
        m.evaluate(m.batch_relations(), m.REPLACE, observe)
        self.assertEqual(len(calls), len(set(calls)))

    def test_calibration_counts_disagreement(self):
        flips = iter([frozenset({('a', 'out')}), frozenset(), frozenset(), frozenset()])
        cal = m.calibrate(m.BATCH, lambda h: next(flips))
        self.assertEqual(cal['false_alarms'], 1)
        self.assertEqual(cal['rate'], 0.5)

    def test_openlineage_distinguishes_omitted_and_empty_complete_inputs(self):
        relations = {r.id: r for r in m.openlineage_relations()}
        explicit_empty = relations['MR9a']
        absent = relations['MR9c']
        self.assertEqual(explicit_empty.a[0][2], 'inputs_in_start')
        self.assertEqual(absent.a[0][2], 'inputs_omitted_complete')
        self.assertEqual(explicit_empty.b, absent.b)
        self.assertIn(m.REPLACE, absent.counted_under)

    def test_openlineage_relations_well_formed(self):
        ids = [r.id for r in m.openlineage_relations()]
        self.assertEqual(len(ids), len(set(ids)))
        for r in m.openlineage_relations():
            self.assertTrue(all(s[0] == 'ol' for s in r.a + r.b))


if __name__ == '__main__':
    unittest.main()
