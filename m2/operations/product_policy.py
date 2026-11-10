"""Fixed browser product defaults; CLI/legacy archive records keep their own provenance."""

MODEL = 'gpt-6-luna'  # Direct Responses; account catalog admission is still required.
REPORTING_ZONE = 'Europe/Copenhagen'


def public_defaults():
    return {'model': MODEL, 'reporting_zone': REPORTING_ZONE}
