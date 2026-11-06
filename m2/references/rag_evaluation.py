"""Small evidence audit: citation identity and literal quote are not claim support.

Run with the owner's Store/session and archived tool-result data. An independent
reader must judge whether the quoted passage actually entails a prose claim.
"""

from m2.references.references import References


def audit_citation(store, session, source_id, passage_id, quoted_text):
    """Check current eligibility and exact quote, without pretending to judge semantics."""
    try:
        row = References(store).readable_passage(session, source_id, passage_id)
    except (KeyError, PermissionError):
        return {'identity': 'unavailable', 'literal_quote': False,
                'claim_support': 'not_assessed'}
    return {'identity': 'eligible', 'literal_quote': (
        isinstance(quoted_text, str) and bool(quoted_text) and
        quoted_text in row['content']), 'claim_support': 'not_assessed',
        'source_status': row['source_status'], 'content_sha256': row['content_sha256']}
