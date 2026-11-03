"""Bounded owned hybrid recall; model scores are relevance hints, not support.

Embeddings are offline, locally computed, rebuildable PostgreSQL derivatives.
An index failure leaves originals available for keyword search and source reads.
"""

from pathlib import Path

from fastembed import TextEmbedding
import numpy as np

from m2.provenance import source_turn_current
from m2.public_model import MODEL, REVISION
from m2.recall import search as search_history


MODEL_ID = f'{MODEL}@{REVISION}:fastembed-0.9.1:prefix2048'
CANDIDATE_LIMIT = 240
MAX_REFERENCE_SCAN = 2400  # bound work when many newer sources are stale


class LocalEmbedder:
    def __init__(self, cache_dir=None):
        cache = cache_dir or Path(__file__).resolve().parents[1] / '.local/models/fastembed'
        self.model = TextEmbedding(MODEL, cache_dir=str(cache),
                                   local_files_only=True, threads=2,
                                   providers=['CPUExecutionProvider'])

    def document(self, text):
        return next(iter(self.model.embed([text[:2048]], batch_size=1))).tolist()

    def query(self, text):
        return next(iter(self.model.query_embed(text))).tolist()


def rebuild_vectors(store, session, embedder, limit=10):
    """Current-reference/history rows only; missing model remains visibly pending."""
    owner = store.owner(session)
    if not 1 <= limit <= 10:
        raise ValueError('Vector rebuild limit 1..10')
    # Page without mutating vectors during selection: changing the query's
    # missing-vector set between OFFSET pages could skip the next valid source.
    candidates, cache, scanned = [], {}, 0
    page = []
    while len(candidates) < limit and scanned < MAX_REFERENCE_SCAN:
        batch = min(CANDIDATE_LIMIT, MAX_REFERENCE_SCAN - scanned)
        page = store.db.execute('''
            SELECT p.source_id,p.id,p.content,p.content_sha256,
                   s.source_conversation_id,s.source_turn_id,s.approval,s.rights_basis
            FROM reference_passages p
            JOIN reference_sources s ON (s.owner_id=p.owner_id AND s.id=p.source_id)
            LEFT JOIN reference_vectors v ON (v.owner_id=p.owner_id AND v.source_id=p.source_id
                                              AND v.passage_id=p.id)
            WHERE p.owner_id=%s AND s.approval<>'revoked'
              AND (s.approval='selected' OR s.rights_basis='synthetic_fixture')
              AND (v.owner_id IS NULL OR v.model_id<>%s
                                    OR v.content_sha256<>p.content_sha256)
            ORDER BY p.source_id,p.id LIMIT %s OFFSET %s
        ''', (owner, MODEL_ID, batch, scanned)).fetchall()
        scanned += len(page)
        candidates.extend(row for row in page if _allowed_source(store, session, row, cache))
        if len(page) < batch:
            break

    indexed_references = 0
    for row in candidates[:limit]:
        vector = embedder.document(row['content'])
        with store.db.transaction():
            store.db.execute('''
                INSERT INTO reference_vectors(owner_id,source_id,passage_id,model_id,content_sha256,embedding)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (owner_id,source_id,passage_id)
                DO UPDATE SET model_id=EXCLUDED.model_id,content_sha256=EXCLUDED.content_sha256,
                              embedding=EXCLUDED.embedding
            ''', (owner, row['source_id'], row['id'], MODEL_ID, row['content_sha256'], vector))
        indexed_references += 1
    remaining = limit - indexed_references
    history = store.db.execute('''
        SELECT e.conversation_id,e.source_id,e.speaker,e.content,e.epoch
        FROM search_entries e JOIN conversations c ON (c.owner_id=e.owner_id AND c.id=e.conversation_id
                                                       AND c.epoch=e.epoch)
        LEFT JOIN history_vectors v ON (v.owner_id=e.owner_id AND v.conversation_id=e.conversation_id
                                       AND v.source_id=e.source_id AND v.speaker=e.speaker)
        WHERE e.owner_id=%s AND (v.owner_id IS NULL OR v.model_id<>%s OR v.epoch<>e.epoch)
        ORDER BY c.created_at DESC,e.source_id LIMIT %s
    ''', (owner, MODEL_ID, remaining)).fetchall() if remaining else []
    for row in history:
        vector = embedder.document(row['content'])
        with store.db.transaction():
            # If the active branch/correction changed while encoding, never
            # stamp a stale vector with the new epoch or overwrite a new row.
            current = store.db.execute('''
                SELECT 1 FROM search_entries e JOIN conversations c
                  ON (c.owner_id=e.owner_id AND c.id=e.conversation_id AND c.epoch=e.epoch)
                WHERE e.owner_id=%s AND e.conversation_id=%s AND e.source_id=%s
                  AND e.speaker=%s AND e.epoch=%s AND e.content=%s
            ''', (owner, row['conversation_id'], row['source_id'], row['speaker'],
                  row['epoch'], row['content'])).fetchone()
            if not current:
                continue
            store.db.execute('''
                INSERT INTO history_vectors(owner_id,conversation_id,source_id,speaker,epoch,
                                            model_id,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (owner_id,conversation_id,source_id,speaker)
                DO UPDATE SET epoch=EXCLUDED.epoch,model_id=EXCLUDED.model_id,
                              embedding=EXCLUDED.embedding
            ''', (owner, row['conversation_id'], row['source_id'], row['speaker'],
                  row['epoch'], MODEL_ID, vector))
    return {'references_indexed': indexed_references, 'history_indexed': len(history),
            'reference_candidates_truncated': scanned >= CANDIDATE_LIMIT,
            'reference_scan_truncated': scanned >= MAX_REFERENCE_SCAN and len(page) == batch}


def _allowed_source(store, session, row, cache):
    """Optional chat-sourced reference must still be current on its branch."""
    if row['approval'] == 'revoked' or (row['approval'] != 'selected' and
                                       row['rights_basis'] != 'synthetic_fixture'):
        return False
    conv_id, turn_id = row['source_conversation_id'], row['source_turn_id']
    if not conv_id:
        return True
    return source_turn_current(store, session, conv_id, turn_id,
                               cache.setdefault('chains', {}),
                               cache.setdefault('resolved', {}))


def search_evidence(store, session, query, embedder=None, limit=8, tradition=None,
                    technique=None, person_id=None, include_history=True,
                    author=None, language=None):
    owner = store.owner(session)
    if not isinstance(query, str) or not 1 <= len(query) <= 256 or not 1 <= limit <= 32:
        raise ValueError('Invalid bounded evidence query')
    for value in (tradition, technique, person_id):
        if value is not None:
            store._id(value)
    if author is not None:
        store._text(author, 256)
    if language is not None and (not isinstance(language, str) or
                                 not 2 <= len(language) <= 12 or not language.isascii()):
        raise ValueError('Invalid reference language')
    if person_id and not store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                                          (owner, person_id)).fetchone():
        raise KeyError('Person not found')

    # FTS candidates include exact matches even when semantic indexing lags.
    # Semantic candidates are bounded explicitly; a corpus-wide nearest-neighbor
    # guarantee is impossible without a vector index and is NOT claimed.
    refs, cache, scanned = [], {}, 0
    while len(refs) < CANDIDATE_LIMIT and scanned < MAX_REFERENCE_SCAN:
        page = store.db.execute('''
            SELECT p.source_id,p.id AS passage_id,p.content,s.author,s.title,s.edition,s.tradition,
                   s.technique,s.provenance,s.rights_basis,s.approval,s.language,s.source_url,
                   l.ordinal,l.page_start,l.page_end,l.printed_page_start,l.printed_page_end,
                   l.source_locator_start,l.source_locator_end,l.parent_section,l.review_status,
                   s.source_conversation_id,
                   s.source_turn_id,v.embedding,
                   to_tsvector('simple',p.content) @@ plainto_tsquery('simple',%s) AS keyword
            FROM reference_passages p JOIN reference_sources s
              ON (s.owner_id=p.owner_id AND s.id=p.source_id)
            LEFT JOIN reference_vectors v ON (v.owner_id=p.owner_id AND v.source_id=p.source_id
                                             AND v.passage_id=p.id AND v.model_id=%s
                                             AND v.content_sha256=p.content_sha256)
            LEFT JOIN reference_book_locations l ON (l.owner_id=p.owner_id
                AND l.source_id=p.source_id AND l.passage_id=p.id)
            WHERE p.owner_id=%s AND s.approval<>'revoked'
              AND (s.approval='selected' OR s.rights_basis='synthetic_fixture')
              AND (%s::text IS NULL OR s.tradition=%s)
              AND (%s::text IS NULL OR s.technique=%s)
              AND (%s::text IS NULL OR s.author=%s)
              AND (%s::text IS NULL OR s.language=%s)
            ORDER BY (to_tsvector('simple',p.content) @@ plainto_tsquery('simple',%s)) DESC,
                     s.created_at DESC,p.source_id,p.id LIMIT %s OFFSET %s
        ''', (query, MODEL_ID, owner, tradition, tradition, technique, technique,
              author, author, language, language, query, CANDIDATE_LIMIT, scanned)).fetchall()
        scanned += len(page)
        refs.extend(row for row in page if _allowed_source(store, session, row, cache))
        if len(page) < CANDIDATE_LIMIT:
            break
    refs = refs[:CANDIDATE_LIMIT]
    history = []
    if (include_history and tradition is None and technique is None and
            author is None and language is None):
        history = store.db.execute('''
            SELECT e.conversation_id,e.source_id,e.speaker,e.content,v.embedding,
                   to_tsvector('simple',e.content) @@ plainto_tsquery('simple',%s) AS keyword
            FROM search_entries e JOIN conversations c
              ON (c.owner_id=e.owner_id AND c.id=e.conversation_id AND c.epoch=e.epoch)
            LEFT JOIN history_vectors v ON (v.owner_id=e.owner_id AND v.conversation_id=e.conversation_id
                                           AND v.source_id=e.source_id AND v.speaker=e.speaker
                                           AND v.epoch=e.epoch AND v.model_id=%s)
            WHERE e.owner_id=%s AND (%s::text IS NULL OR EXISTS (
                SELECT 1 FROM turn_people tp
                WHERE tp.owner_id=e.owner_id AND tp.conversation_id=e.conversation_id
                  AND tp.person_id=%s AND (tp.turn_id=e.source_id OR EXISTS (
                      SELECT 1 FROM corrections correction
                      WHERE correction.owner_id=e.owner_id
                        AND correction.conversation_id=e.conversation_id
                        AND correction.id=e.source_id AND correction.source_turn_id=tp.turn_id))))
            ORDER BY (to_tsvector('simple',e.content) @@
                   plainto_tsquery('simple',%s)) DESC,c.created_at DESC,e.source_id LIMIT %s
        ''', (query, MODEL_ID, owner, person_id, person_id, query,
              CANDIDATE_LIMIT)).fetchall()
    query_vec = np.array(embedder.query(query), dtype=np.float32) if embedder else None
    scored = []
    for row in refs:
        score = (1.0 if row['keyword'] else 0.0)
        if query_vec is not None and row['embedding'] is not None:
            score += float(np.dot(query_vec, np.array(row['embedding'], dtype=np.float32)))
        if score > 0:
            scored.append((score, {'kind': 'reference_passage', 'source_id': row['source_id'],
                'passage_id': row['passage_id'], 'excerpt': row['content'][:600],
                'author': row['author'], 'title': row['title'], 'edition': row['edition'],
                'tradition': row['tradition'], 'technique': row['technique'],
                'language': row['language'], 'source_url': row['source_url'],
                'ordinal': row['ordinal'], 'page_start': row['page_start'],
                'page_end': row['page_end'],
                'printed_page_start': row['printed_page_start'],
                'printed_page_end': row['printed_page_end'],
                'source_locator_start': row['source_locator_start'],
                'source_locator_end': row['source_locator_end'],
                'parent_section': row['parent_section'],
                'review_status': row['review_status'],
                'provenance': row['provenance'], 'rights_basis': row['rights_basis'],
                'approval': row['approval'], 'keyword_match': row['keyword'],
                'source_kind': 'source_not_verified_interpretation'}))
    for row in history:
        score = (1.0 if row['keyword'] else 0.0)
        if query_vec is not None and row['embedding'] is not None:
            score += float(np.dot(query_vec, np.array(row['embedding'], dtype=np.float32)))
        if score > 0:
            scored.append((score, {'kind': 'conversation', 'conversation_id': row['conversation_id'],
                'source_id': row['source_id'], 'speaker': row['speaker'],
                'excerpt': row['content'][:600], 'keyword_match': row['keyword'],
                'source_kind': 'prior_statement_not_independent_evidence'}))
    scored.sort(key=lambda item: item[0], reverse=True)
    count = store.db.execute('''
        SELECT (SELECT count(*) FROM reference_passages p JOIN reference_sources s
                 ON (s.owner_id=p.owner_id AND s.id=p.source_id)
                 WHERE p.owner_id=%s AND s.approval<>'revoked'
                   AND (s.approval='selected' OR s.rights_basis='synthetic_fixture')
                   AND (%s::text IS NULL OR s.tradition=%s)
                   AND (%s::text IS NULL OR s.technique=%s)
                   AND (%s::text IS NULL OR s.author=%s)
                   AND (%s::text IS NULL OR s.language=%s)) AS references,
               (SELECT count(*) FROM reference_passages p JOIN reference_sources s
                   ON (s.owner_id=p.owner_id AND s.id=p.source_id)
                 LEFT JOIN reference_vectors v ON (v.owner_id=p.owner_id AND v.source_id=p.source_id
                   AND v.passage_id=p.id AND v.model_id=%s AND v.content_sha256=p.content_sha256)
                 WHERE p.owner_id=%s AND v.owner_id IS NULL AND s.approval<>'revoked'
                   AND (s.approval='selected' OR s.rights_basis='synthetic_fixture')
                   AND (%s::text IS NULL OR s.tradition=%s)
                   AND (%s::text IS NULL OR s.technique=%s)
                   AND (%s::text IS NULL OR s.author=%s)
                   AND (%s::text IS NULL OR s.language=%s)) AS unindexed_references,
               (SELECT count(*) FROM search_entries e JOIN conversations c
                 ON (c.owner_id=e.owner_id AND c.id=e.conversation_id AND c.epoch=e.epoch)
                 WHERE e.owner_id=%s AND (%s::text IS NULL OR EXISTS (
                     SELECT 1 FROM turn_people tp
                     WHERE tp.owner_id=e.owner_id AND tp.conversation_id=e.conversation_id
                       AND tp.person_id=%s AND (tp.turn_id=e.source_id OR EXISTS (
                           SELECT 1 FROM corrections correction
                           WHERE correction.owner_id=e.owner_id
                             AND correction.conversation_id=e.conversation_id
                             AND correction.id=e.source_id
                             AND correction.source_turn_id=tp.turn_id))))) AS history
    ''', (owner, tradition, tradition, technique, technique,
          author, author, language, language,
          MODEL_ID, owner, tradition, tradition, technique, technique,
          author, author, language, language,
          owner, person_id, person_id)).fetchone()
    lag = search_history(store, session, query, 1)['pending_conversations']
    selected = [dict(item, score=round(score, 4)) for score, item in scored[:limit]]
    reference_scan_truncated = scanned >= MAX_REFERENCE_SCAN and count['references'] > scanned
    evidence_status = ('keyword_matches' if any(row['keyword_match'] for row in selected)
                       else 'semantic_suggestions_only' if selected else
                       'incomplete_candidate_scan' if reference_scan_truncated else 'not_found')
    return {'results': selected, 'evidence_status': evidence_status,
            'pending_conversations': lag, 'semantic_available': query_vec is not None,
            'semantic_index_incomplete': bool(count['unindexed_references']),
            'person_filter': person_id,
            'history_excluded_for_person_filter': False,
            'semantic_candidates_truncated': count['references'] > CANDIDATE_LIMIT or
                                              count['history'] > CANDIDATE_LIMIT,
            'candidate_limit_per_kind': CANDIDATE_LIMIT,
            'reference_scan_truncated': reference_scan_truncated,
            'reference_scan_limit': MAX_REFERENCE_SCAN, 'limit': limit}


def personal_context(store, session, person_id, limit=10):
    owner = store.owner(session)
    if not 1 <= limit <= 10:
        raise ValueError('Personal context limit 1..10')
    if not store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                            (owner, store._id(person_id))).fetchone():
        raise KeyError('Person not found')
    rows = store.db.execute('''
        SELECT p.id,p.conversation_id,p.source_turn_id,p.source_event_sequence,p.statement,
               p.epistemic_status,p.confirmation_turn_id,p.created_at,a.note,a.action
        FROM personal_entries p LEFT JOIN LATERAL (
            SELECT note,action FROM personal_entry_actions WHERE owner_id=p.owner_id
              AND person_id=p.person_id AND entry_id=p.id
            ORDER BY created_at DESC,id DESC LIMIT 1
        ) a ON true WHERE p.owner_id=%s AND p.person_id=%s AND COALESCE(a.action,'save')!='remove'
        ORDER BY p.created_at DESC,p.id DESC LIMIT %s
    ''', (owner, person_id, CANDIDATE_LIMIT)).fetchall()
    cache, validity = {}, {}
    active = []
    for row in rows:
        row.pop('action')
        conv_id = row['conversation_id']
        if conv_id not in cache:
            head = store.active_head(session, conv_id)
            cache[conv_id] = set(store.ancestry(session, conv_id, head)) if head else set()
        chain = cache[conv_id]
        if (row['source_turn_id'] not in chain or
                row['confirmation_turn_id'] and row['confirmation_turn_id'] not in chain):
            continue
        if (not source_turn_current(store, session, conv_id, row['source_turn_id'],
                                    cache, validity) or
                row['confirmation_turn_id'] and
                not source_turn_current(store, session, conv_id,
                                        row['confirmation_turn_id'], cache, validity)):
            continue
        active.append(row)
        if len(active) == limit:
            break
    return {'entries': active, 'candidate_limit': CANDIDATE_LIMIT,
            'candidates_truncated': len(rows) == CANDIDATE_LIMIT}
