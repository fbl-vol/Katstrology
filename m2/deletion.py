"""Installed release retention contract: keep m2.deletion.Tombstones importable.

The immutable release helper embeds this import when retaining deletion authority.
Application callers use m2.archive.deletion directly; this is not a second journal.
"""
from m2.archive.deletion import Tombstones

__all__ = ['Tombstones']
