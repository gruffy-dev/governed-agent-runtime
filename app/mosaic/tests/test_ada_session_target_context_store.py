import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from mosaic.components.orchestration.ada_session_target_context_store import AdaSessionTargetContextStore


class TestAdaSessionTargetContextStore(unittest.TestCase):
    def test_target_can_be_set_read_and_cleared(self) -> None:
        store = AdaSessionTargetContextStore()
        context = SimpleNamespace(state={})

        stored = store.set(context, 'openshift/cluster1')

        self.assertEqual(stored.target_id, 'openshift/cluster1')
        self.assertEqual(store.get(context), stored)
        store.clear(context)
        self.assertIsNone(store.get(context))

    def test_malformed_persisted_target_is_rejected(self) -> None:
        store = AdaSessionTargetContextStore()
        context = SimpleNamespace(
            state={
                'mosaic:session-target': {
                    'schema_version': 1,
                    'target_id': 'invalid',
                }
            }
        )

        with self.assertRaises(ValidationError):
            store.get(context)


if __name__ == '__main__':
    unittest.main()
