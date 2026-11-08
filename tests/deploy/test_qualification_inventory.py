"""Identity completeness and strict native outcomes, not green-count inference."""
from copy import deepcopy
import unittest

from deploy.qualification_inventory import check_execution, complete_shards, inventory


def discovery(*ids):
    return {'workers': 1, 'status': 'passed', 'errors': 0,
            'tests': [{'id': str(i) * 64, 'allowedSkip': False, 'outcomes': []} for i in ids]}


class InventoryTests(unittest.TestCase):
    def test_disjoint_native_union_and_exact_execution(self):
        full = discovery(1, 2, 3, 4)
        complete_shards(full, [discovery(1), discovery(2, 3), discovery(4)])
        executed = deepcopy(full)
        for test in executed['tests']:
            test['outcomes'] = ['passed']
        check_execution(full, executed)

    def test_duplicate_missing_and_foreign_identities_are_not_complete(self):
        for parts in ([discovery(1), discovery(1, 2)], [discovery(1)], [discovery(1, 3)]):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                complete_shards(discovery(1, 2), parts)
        with self.assertRaises(ValueError):
            inventory(discovery(1, 1))

    def test_failed_retried_skipped_missing_or_other_execution_is_rejected(self):
        for outcomes in ([], ['failed'], ['skipped'], ['failed', 'passed'], ['passed', 'passed']):
            executed = discovery(1)
            executed['tests'][0]['outcomes'] = outcomes
            with self.subTest(outcomes=outcomes), self.assertRaises(ValueError):
                check_execution(discovery(1), executed)
        executed = discovery(2)
        executed['tests'][0]['outcomes'] = ['passed']
        with self.assertRaises(ValueError):
            check_execution(discovery(1), executed)

    def test_established_skip_requires_same_discovered_identity_and_contract(self):
        full = discovery(1)
        full['tests'][0]['allowedSkip'] = True
        executed = deepcopy(full)
        executed['tests'][0]['outcomes'] = ['skipped']
        check_execution(full, executed)
        with self.assertRaises(ValueError):
            check_execution(discovery(1), executed)
        for field, value in [('status', 'interrupted'), ('errors', 1), ('workers', 2)]:
            broken = deepcopy(full)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                inventory(broken)
