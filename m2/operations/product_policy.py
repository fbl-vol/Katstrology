"""Fixed browser product defaults; CLI/legacy archive records keep their own provenance."""

MODEL = 'gpt-6.1-sol'  # Existing selected ChatGPT-plan direct Responses route.
REPORTING_ZONE = 'Europe/Copenhagen'


def public_defaults():
    return {'model': MODEL, 'reporting_zone': REPORTING_ZONE}
