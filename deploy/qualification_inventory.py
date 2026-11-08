"""Native Playwright inventory contracts shared by local validation and CI join."""

import json
from pathlib import Path
import re


def read_json(path):
    with Path(path).open() as source:
        text = source.read(4 * 1024 * 1024 + 1)
    if len(text) > 4 * 1024 * 1024:
        raise ValueError('Oversized qualification evidence')
    return json.loads(text)


def inventory(report, *, executed=False):
    if report['status'] != 'passed' or report['errors'] != 0 or report['workers'] != 1:
        raise ValueError('Native discovery/execution failed or changed worker count')
    tests = report['tests']
    ids = [test['id'] for test in tests]
    if (not ids or len(ids) != len(set(ids))
            or any(not re.fullmatch('[0-9a-f]{64}', value) for value in ids)):
        raise ValueError('Empty, duplicate or invalid native test identities')
    for test in tests:
        if type(test['allowedSkip']) is not bool:
            raise ValueError('Invalid skip contract')
        expected = ['skipped'] if test['allowedSkip'] else ['passed']
        if test['outcomes'] != (expected if executed else []):
            raise ValueError('Missing, failed, skipped or retried test')
    return {test['id']: test['allowedSkip'] for test in tests}


def check_execution(discovered, executed):
    if inventory(discovered) != inventory(executed, executed=True):
        raise ValueError('Executed tests differ from native discovery')


def complete_shards(full, parts):
    expected = inventory(full)
    actual = {}
    for part in parts:
        selected = inventory(part)
        if actual.keys() & selected.keys():
            raise ValueError('Duplicate tests across browser shards')
        actual.update(selected)
    if actual != expected:
        raise ValueError('Shard union differs from complete browser inventory')
