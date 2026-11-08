"""Shared owned-person recognition labels for picker pages and existing links."""

# Rank before page/search/link filtering so every consumer sees the same ordinal.
# Only the authenticated owner's people participate, including in name counts.
OWNED_CHOICES_CTE = '''WITH person_choices AS (
    SELECT p.id,p.name,p.created_at,d.details,
        count(*) OVER (PARTITION BY lower(p.name)) AS name_count,
        row_number() OVER (PARTITION BY lower(p.name) ORDER BY p.created_at,p.id) AS name_number
    FROM people p LEFT JOIN personal_details d
        ON d.owner_id=p.owner_id AND d.person_id=p.id
    WHERE p.owner_id=%s)
'''


def picker_label(row):
    label = row['name']
    if row['name_count'] > 1:
        details = row['details'] or {}
        description = ', '.join(details.get(key, '').strip() for key in ('occupation', 'home')
                                if details.get(key, '').strip())
        # Local ordinal is a recognition aid, never identity authority.
        preview = description[:80] or 'added ' + row['created_at'].strftime('%d %b %Y')
        label += f" · {preview} (profile {row['name_number']})"
    return label
