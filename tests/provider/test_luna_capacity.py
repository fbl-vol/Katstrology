"""Luna bounds are independently evidenced; historical Sol remains readable."""
import unittest

from m2.operations.product_policy import MODEL
from m2.provider.model_capacity import CATALOG, DOCS, resolve_capacity
from m2.provider.siwc import ProviderFailure


class LunaCapacityTests(unittest.TestCase):
    def test_product_default_and_independent_documented_bounds(self):
        self.assertEqual(MODEL, 'gpt-6-luna')
        capacity = resolve_capacity({'slug': MODEL})
        self.assertEqual((capacity.context_window, capacity.max_output_tokens), (1_050_000, 128_000))
        self.assertEqual(capacity.source, DOCS)
        self.assertFalse(capacity.route_verified)
        historical = resolve_capacity({'slug': 'gpt-6.1-sol'})
        self.assertEqual((historical.context_window, historical.max_output_tokens), (1_050_000, 128_000))

    def test_each_catalog_bound_is_independent(self):
        for metadata, context_source, output_source in (
            ({'context_window': 200_000}, CATALOG, DOCS),
            ({'max_output_tokens': 16_000}, DOCS, CATALOG),
            ({'context_window': 200_000, 'max_output_tokens': 16_000}, CATALOG, CATALOG),
        ):
            with self.subTest(metadata=metadata):
                capacity = resolve_capacity({'slug': MODEL, **metadata})
                self.assertEqual(capacity.context_window, metadata.get('context_window', 1_050_000))
                self.assertEqual(capacity.max_output_tokens, metadata.get('max_output_tokens', 128_000))
                self.assertEqual((capacity.context_source, capacity.output_source), (context_source, output_source))

    def test_invalid_metadata_never_becomes_documented_fallback(self):
        for metadata in ({'context_window': None}, {'context_window': True},
                         {'context_window': '100000'}, {'context_window': 1_050_001},
                         {'max_output_tokens': 128_001}, {'max_output_tokens': None},
                         {'context_window': 4096, 'max_output_tokens': 4096}):
            with self.subTest(metadata=metadata), self.assertRaises(ProviderFailure):
                resolve_capacity({'slug': MODEL, **metadata})
        with self.assertRaises(ProviderFailure):
            resolve_capacity({'slug': 'unknown-model'})
