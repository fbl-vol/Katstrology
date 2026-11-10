"""Constituent conversation sources retained through automatic consolidation."""
MAX_SOURCES = 8


def references(source):
    if source.get('kind') != 'conversation':
        return []
    return source.get('sources', [source])
