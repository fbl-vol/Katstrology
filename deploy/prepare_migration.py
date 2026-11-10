"""Offline exact additive lane from public source directories; no database/host access."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from deploy.release_access import validate_transition_lane
from m2.release_schema import migration_files


def history(directory):
    paths = sorted(directory.glob('[0-9]*.sql'))
    if (not paths or any(path.is_symlink() for path in paths)
            or [int(path.name.split('_')[0]) for path in paths] != list(range(1, len(paths) + 1))):
        raise ValueError('Exact contiguous public migration history required')
    return {path.name: sha256(path.read_bytes()).hexdigest() for path in paths}


def prepare(before, candidate, policy=None):
    old, new = history(before), history(candidate)
    if len(new) < len(old) or any(new.get(name) != digest for name, digest in old.items()):
        raise ValueError('Retained migration history changed or regressed')
    lane = None
    if len(new) > len(old):
        lane = {'from': len(old), 'to': len(new),
                'migrations': {name: digest for name, digest in new.items() if name not in old},
                'added_tables': [], 'added_columns': {}}
        for name in lane['migrations']:
            statement = (candidate / name).read_text().strip()
            table = re.match(r'CREATE TABLE ([a-z_][a-z_0-9]*)\s*\(', statement)
            column = re.match(r'ALTER TABLE ([a-z_][a-z_0-9]*) ADD COLUMN ([a-z_][a-z_0-9]*) ', statement)
            if table:
                lane['added_tables'].append(table[1])
            elif column:
                lane['added_columns'].setdefault(column[1], []).append(column[2])
            else:
                raise ValueError('Unsupported additive statement; migration decision required')
        lane['added_tables'].sort()
        if len(set(lane['added_tables'])) != len(lane['added_tables']):
            raise ValueError('Duplicate new table')
        validate_transition_lane(lane)
        migration_files(candidate, lane)  # Same exact SQL grammar used by native migration.
    installed = policy is not None and lane in policy['transitions']
    return {'contract': 1, 'status': 'offline-prepared', 'from': len(old), 'to': len(new),
            'history_sha256': new, 'lane': lane,
            'lane_sha256': sha256(lane_bytes(lane)).hexdigest() if lane else None,
            'enrollment': 'not-needed' if lane is None else
                          'present-in-supplied-policy-not-live-verified' if installed else 'required',
            'limits': ['No live schema, ownership or installed-policy observation',
                       'Native snapshot/transaction/preservation checks remain mandatory']}


def lane_bytes(lane):
    return (json.dumps(lane, sort_keys=True, indent=2) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True, help='Supplied old public migration directory')
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--policy', type=Path, help='Optional supplied CI policy; never auto-read installed policy')
    parser.add_argument('--lane-output', type=Path, help='Exclusively create exact lane bytes for future approval')
    args = parser.parse_args()
    result = prepare(args.before, args.candidate, json.loads(args.policy.read_text()) if args.policy else None)
    if args.lane_output and result['lane'] is not None:
        with args.lane_output.open('xb') as output:
            output.write(lane_bytes(result['lane']))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
