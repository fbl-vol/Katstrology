"""Fail-closed join of trusted qualification lanes; no build, upload or activation.

Lane files are transported by run/attempt-scoped GitHub artifacts, not accepted
as arbitrary user attestations. Native discovery is repeated by the joining job.
The public qualification witness remains compatible with existing consumers.
"""

import json
from pathlib import Path
import re

from deploy.qualification_inventory import read_json, inventory, check_execution, complete_shards
from deploy.release_pipeline import artifact, digest

PROFILES = ('backend', 'probes', 'browser', 'siwc', 'clock')
LANES = {'backend': ('backend', 'probes'), 'interaction': ('siwc', 'clock'),
         **{f'browser-{i}': ('browser',) for i in range(1, 5)}}


def validate_synthetic(report, identity, profiles, shard=None):
    if (report['action'] != 'execute' or report['status'] != 'ok' or report['unrun']
            or report['git'] != {'sha': identity['commit'], 'dirty': False}
            or report['tree'] != identity['tree'] or report['selected'] != list(profiles)
            or set(report['results']) != set(profiles)
            or report['filters'] != {'tests': [], 'browser_grep': None, 'private_layout_reference': False}
            or report['browser_shard'] != shard or report['inventory_only']
            or report['fixture'] != 'owned-isolated-loopback'
            or report['fixture_cleanup'] != 'owned-container-removed'):
        raise ValueError('Incomplete, filtered, dirty or foreign synthetic lane')
    for profile in profiles:
        result = report['results'][profile]
        if result['status'] != 'passed':
            raise ValueError('Unsuccessful profile')
        if profile in ('browser', 'siwc', 'clock'):
            check_execution(result['inventory'], result['executed'])
            if profile != 'siwc' and any(inventory(result['inventory']).values()):
                raise ValueError('Unexpected skip permission')
        elif profile == 'backend':
            diagnostics = result['diagnostics']
            if diagnostics['tests_run'] < 1 or diagnostics['failure_count'] != 0 or diagnostics['status'] != 'passed':
                raise ValueError('Backend execution evidence incomplete')
        elif not any(re.fullmatch(r'Ran [1-9][0-9]* tests?', value) for value in result['summary']):
            raise ValueError('Probe execution evidence absent')


def write_lane(folder, lane, identity, report_path, *, receipt_path=None):
    record = {'contract': 1, 'lane': lane, 'identity': identity,
              'report_sha256': digest(report_path)}
    if receipt_path is not None:
        record['receipt_sha256'] = digest(receipt_path)
    with (folder / 'evidence.json').open('x') as output:
        json.dump(record, output, sort_keys=True)


def load_lanes(paths, identity):
    lanes = {}
    for path in paths:
        record = read_json(path)
        if (record['contract'] != 1 or record['identity'] != identity
                or record['lane'] in lanes):
            raise ValueError('Foreign source/run/attempt or duplicate lane')
        report_path = path.with_name('report.json')
        if path.is_symlink() or report_path.is_symlink() or digest(report_path) != record['report_sha256']:
            raise ValueError('Altered or indirect lane evidence')
        lanes[record['lane']] = (record, read_json(report_path), report_path)
    return lanes


def assemble(paths, identity, discovered, receipt_path, reports, *, sequential=False):
    lanes = load_lanes(paths, identity)
    expected = {'all', 'native'} if sequential else set(LANES) | {'native'}
    if set(lanes) != expected:
        raise ValueError('Required lane set incomplete or unexpected')
    profiles = {'all': PROFILES} if sequential else LANES
    merged = {}
    browser_parts = []
    for lane, selected in profiles.items():
        _, report, _ = lanes[lane]
        shard = lane.removeprefix('browser-') + '/4' if lane.startswith('browser-') else None
        validate_synthetic(report, identity, selected, shard)
        for profile, result in report['results'].items():
            if profile == 'browser':
                browser_parts.append(result['inventory'])
                merged.setdefault(profile, []).append(result)
            else:
                merged[profile] = result
    complete_shards(discovered, browser_parts)
    native_record, native, native_path = lanes['native']
    # This rechecks archive/source contents; never rewrites a receipt or image.
    receipt, _, _, _ = artifact(receipt_path)
    if (receipt['commit'] != identity['commit'] or receipt['tree'] != identity['tree']
            or digest(receipt_path) != native_record['receipt_sha256']
            or native['status'] != 'passed' or native['cleanup'] != 'passed'
            or native['commit'] != receipt['commit']
            or native['image_id'] != receipt['image_id']
            or native['archive_image_id'] != receipt['image_id']
            or native['config_digest'] != receipt['config_digest']):
        raise ValueError('Native qualification differs from exact immutable package')
    summary = {'status': 'ok', 'identity': identity, 'selected': list(PROFILES),
               'unrun': [], 'results': merged, 'inventory': discovered,
               'lane_reports': {lane: record['report_sha256'] for lane, (record, _, _) in lanes.items()}}
    reports.mkdir(parents=True, exist_ok=False)
    synthetic_path = reports / 'synthetic.json'
    synthetic_path.write_text(json.dumps(summary, sort_keys=True) + '\n')
    witness = {key: receipt[key] for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256')}
    witness.update(receipt_sha256=digest(receipt_path), synthetic_report_sha256=digest(synthetic_path),
                   native_report_sha256=digest(native_path))
    with receipt_path.with_name('qualification.json').open('x') as output:
        json.dump(witness, output, sort_keys=True)
        output.write('\n')
    return witness
