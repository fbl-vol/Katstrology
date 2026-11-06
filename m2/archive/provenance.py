"""Current-source validity across selected turn ancestry and linked evidence.

An original tool source is invalid after correction. Conversational descendants
instead record their direct parent's correction revision at generation: older
answers are historical, while new replies can use the replacement as context.
"""

MAX_SOURCE_NODES = 2000


def _linked_sources(store, owner, conv_id, turn_id):
    return store.db.execute('''
        SELECT DISTINCT b.source_conversation_id AS conversation_id,
                        b.source_turn_id AS turn_id FROM chart_evidence e
        JOIN charts c ON c.owner_id=e.owner_id AND c.id=e.chart_id
        JOIN birth_records b ON b.owner_id=c.owner_id AND b.person_id=c.person_id
                            AND b.id=c.birth_id
        WHERE e.owner_id=%s AND e.conversation_id=%s AND e.turn_id=%s
          AND b.source_conversation_id IS NOT NULL
        UNION
        SELECT DISTINCT s.source_conversation_id, s.source_turn_id
        FROM reference_evidence e JOIN reference_sources s
          ON s.owner_id=e.owner_id AND s.id=e.source_id
        WHERE e.owner_id=%s AND e.conversation_id=%s AND e.turn_id=%s
          AND s.source_conversation_id IS NOT NULL
    ''', (owner, conv_id, turn_id, owner, conv_id, turn_id)).fetchall()


def _turn_record(store, owner, conv_id, turn_id):
    return store.db.execute('''
        SELECT t.parent_id,t.parent_revision,
               (SELECT c.sequence FROM corrections c WHERE c.owner_id=t.owner_id
                  AND c.conversation_id=t.conversation_id AND c.source_turn_id=t.id
                  ORDER BY c.sequence DESC LIMIT 1) AS latest_revision,
               (SELECT c.parent_revision FROM corrections c WHERE c.owner_id=t.owner_id
                  AND c.conversation_id=t.conversation_id AND c.source_turn_id=t.id
                  ORDER BY c.sequence DESC LIMIT 1) AS corrected_parent_revision,
               (SELECT c.action FROM corrections c WHERE c.owner_id=t.owner_id
                  AND c.conversation_id=t.conversation_id AND c.source_turn_id=t.id
                  ORDER BY c.sequence DESC LIMIT 1) AS latest_action,
               EXISTS (SELECT 1 FROM turn_people p JOIN person_drafts d
                 ON d.owner_id=p.owner_id AND d.person_id=p.person_id
                 WHERE p.owner_id=t.owner_id AND p.conversation_id=t.conversation_id
                   AND p.turn_id=t.id AND p.draft_revision IS NOT NULL
                   AND d.revision > p.draft_revision) AS stale_draft,
               EXISTS (SELECT 1 FROM reference_evidence e JOIN reference_sources s
                 ON s.owner_id=e.owner_id AND s.id=e.source_id
                 WHERE e.owner_id=t.owner_id AND e.conversation_id=t.conversation_id
                   AND e.turn_id=t.id AND s.approval='revoked') AS revoked_reference
        FROM turns t WHERE t.owner_id=%s AND t.conversation_id=%s AND t.id=%s
    ''', (owner, conv_id, turn_id)).fetchone()


def _lineage_current(store, session, conv_id, turn_id, chains, resolved, original,
                     allow_historical_drafts=False):
    owner = store.owner(session)
    origin = (conv_id, turn_id, original, allow_historical_drafts)
    if origin in resolved:
        return resolved[origin]

    active, visited = set(), set()
    stack = [(origin, False)]
    while stack:
        key, leaving = stack.pop()
        if leaving:
            active.remove(key)
            continue
        if key in resolved:
            if not resolved[key]:
                resolved[origin] = False
                return False
            continue
        if key in active:
            resolved[origin] = False
            return False
        if key in visited:
            continue
        if len(visited) >= MAX_SOURCE_NODES:
            raise ValueError('Source lineage exceeds supported limit')
        source_conv, source_turn, require_original, allow_drafts = key
        if source_conv not in chains:
            head = store.active_head(session, source_conv)
            chains[source_conv] = set(store.ancestry(session, source_conv, head)) if head else set()
        if source_turn not in chains[source_conv]:
            resolved[origin] = False
            return False
        row = _turn_record(store, owner, source_conv, source_turn)
        if (not row or (require_original and row['latest_revision'] is not None)
                or row['latest_action'] == 'withdraw'
                or (row['stale_draft'] and row['latest_revision'] is None and not allow_drafts)
                or (row['revoked_reference'] and row['latest_revision'] is None)):
            resolved[origin] = False
            return False

        dependencies = []
        if row['parent_id']:
            parent = _turn_record(store, owner, source_conv, row['parent_id'])
            parent_revision = (row['corrected_parent_revision']
                               if row['latest_revision'] is not None else row['parent_revision'])
            if not parent or (parent_revision is None and parent['latest_revision'] is not None):
                resolved[origin] = False
                return False
            if (parent_revision is not None and
                    parent_revision != (parent['latest_revision'] or 0)):
                resolved[origin] = False
                return False
            dependencies.append((source_conv, row['parent_id'], False, allow_drafts))
        if row['latest_revision'] is None:
            dependencies.extend((item['conversation_id'], item['turn_id'], True, False)
                                for item in _linked_sources(store, owner, source_conv, source_turn))
        # A correction replaces the original evidence/reply, so the new text
        # cannot inherit the old turn's tool-result links. Its parent still must
        # match the revision consumed when the correction was committed.
        visited.add(key)
        active.add(key)
        stack.append((key, True))
        stack.extend((dependency, False) for dependency in dependencies)

    resolved.update({key: True for key in visited})
    return True


def source_turn_current(store, session, conv_id, turn_id, chains=None, resolved=None):
    """An immutable source turn must be uncorrected and current on its branch."""
    return _lineage_current(store, session, conv_id, turn_id,
                            {} if chains is None else chains,
                            {} if resolved is None else resolved, True)


def current_turn_usable(store, session, conv_id, turn_id, chains=None, resolved=None):
    """A corrected replacement may support a newly generated descendant."""
    return _lineage_current(store, session, conv_id, turn_id,
                            {} if chains is None else chains,
                            {} if resolved is None else resolved, False)


def dialogue_turn_usable(store, session, conv_id, turn_id, chains=None, resolved=None):
    """Branch/correction/revocation safe continuity, not factual eligibility.

    Only selected draft revisions may be historical; linked evidence retains the
    strict original-source rule. Consumers must still fence stale assistant facts.
    """
    return _lineage_current(store, session, conv_id, turn_id,
                            {} if chains is None else chains,
                            {} if resolved is None else resolved, False, True)
