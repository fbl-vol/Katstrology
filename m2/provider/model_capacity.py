"""Route-scoped hosted capacity evidence, never a tokenizer or a grant promise.

The public OpenAI Models endpoint documents only id/created/object/owned_by.
Plan catalog limit extensions are independently optional. A documented fallback
for a named model is not verification of the user's direct-plan grant.
"""

from dataclasses import dataclass

from m2.provider.siwc import ProviderFailure


# https://developers.openai.com/api/docs/models/gpt-6.1-sol
# API model specification, NOT verification of the user's direct plan grant.
API_SOL_CONTEXT = 1_050_000
API_SOL_MAX_OUTPUT = 128_000
# Independently checked Luna specification (2026-11-10), not inherited Sol limits:
# https://developers.openai.com/api/docs/models/gpt-6-luna
API_LUNA_CONTEXT = 1_050_000
API_LUNA_MAX_OUTPUT = 128_000
DOCUMENTED_BOUNDS = {
    'gpt-6.1-sol': (API_SOL_CONTEXT, API_SOL_MAX_OUTPUT),
    'gpt-6-luna': (API_LUNA_CONTEXT, API_LUNA_MAX_OUTPUT),
}
CATALOG = 'provider_catalog_limits'
DOCS = 'openai_api_model_docs_direct_plan_unverified'


@dataclass(frozen=True)
class Capacity:
    context_window: int
    max_output_tokens: int
    context_source: str
    output_source: str

    @property
    def source(self):
        if self.context_source == self.output_source:
            return self.context_source
        if self.context_source == CATALOG:
            return 'mixed_catalog_context_documented_output'
        return 'mixed_documented_context_catalog_output'

    @property
    def route_verified(self):
        return self.context_source == self.output_source == CATALOG

    @property
    def context_route_verified(self):
        return self.context_source == CATALOG

    @property
    def output_route_verified(self):
        return self.output_source == CATALOG


@dataclass(frozen=True)
class CatalogAdmission:
    """One owner's validated model bounds, fenced to the selected credential state."""

    owner: str
    slug: str
    binding: str
    capacity: Capacity


def resolve_capacity(model):
    slug = model['slug']
    documented = DOCUMENTED_BOUNDS.get(slug)
    has_window = 'context_window' in model
    has_output = 'max_output_tokens' in model
    window = model.get('context_window') if has_window else None
    output = model.get('max_output_tokens') if has_output else None

    # Reject malformed present metadata; never treat null/bool/string as absence.
    if ((has_window and (type(window) is not int or not 2048 <= window <= 2_000_000)) or
            (has_output and (type(output) is not int or output < 1)) or
            (documented is not None and (
                (has_window and window > documented[0]) or
                (has_output and output > documented[1])))):
        raise ProviderFailure('invalid_model_context_metadata')
    if documented is None and not (has_window and has_output):
        raise ProviderFailure('model_context_capacity_unknown')

    context_source = CATALOG if has_window else DOCS
    output_source = CATALOG if has_output else DOCS
    window = window if has_window else documented[0]
    output = output if has_output else documented[1]
    # An advertised output >= window is inconsistent. A documented maximum
    # may exceed a smaller route window: it remains a ceiling, not a reserve.
    if has_output and output >= window:
        raise ProviderFailure('invalid_model_context_metadata')
    return Capacity(window, output, context_source, output_source)
