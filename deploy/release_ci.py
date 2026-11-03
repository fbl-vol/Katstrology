"""Prepare/execute a keyless release of an already qualified immutable package.

The target descriptor is public scope + an enrolled fingerprint, not private host
paths. Preparation never signs, uploads or opens SSH. Execute uses only the fixed
CI forced command and the existing phase controller; no deployment rebuild.
"""

import argparse
import json
from pathlib import Path
import re
from uuid import uuid4

from deploy import release_pipeline as pipeline
from deploy.release_ci_access import canonical, validate_manifest


def prepare(receipt_path, descriptor, run_id):
    if set(descriptor) != {'project', 'origin', 'loopback_port', 'target_sha256'}:
        raise ValueError('Public target descriptor fields differ')
    if (not pipeline.PROJECT.fullmatch(descriptor['project'])
            or not re.fullmatch(r'https://[a-z0-9.-]+', descriptor['origin'])
            or not pipeline.HEX.fullmatch(descriptor['target_sha256'])
            or descriptor['loopback_port'] not in range(1024, 65536)):
        raise ValueError('Invalid public scope')
    receipt, archive, compose, schema = pipeline.artifact(receipt_path)
    qualification = json.loads(receipt_path.with_name('qualification.json').read_text())
    for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256'):
        if qualification[key] != receipt[key]:
            raise ValueError('Candidate differs from qualified bytes')
    if qualification['receipt_sha256'] != pipeline.digest(receipt_path):
        raise ValueError('Candidate receipt changed after qualification')
    plan = pipeline.plan_for_scope(receipt, descriptor, schema, compose, uuid4().hex,
                                  archive.stat().st_size, Path(receipt['source_offer']).stat().st_size)
    manifest = {'contract': 1, 'plan': plan, 'run_id': run_id, 'run_attempt': 1}
    validate_manifest(manifest)
    return manifest


def execute(receipt_path, manifest_path, bundle, ssh_config, result):
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)
    if manifest_path.read_bytes() != canonical(manifest):
        raise ValueError('Manifest must retain exact attested canonical bytes')
    receipt, archive, compose, schema = pipeline.artifact(receipt_path)
    plan = manifest['plan']
    expected = pipeline.plan_for_scope(receipt, plan['target'], schema, compose, plan['attempt'],
                                      archive.stat().st_size, Path(receipt['source_offer']).stat().st_size)
    if plan != expected:
        raise ValueError('Manifest/artifact/helper handoff changed')
    # The dedicated enrolled profile pins hostname/user/key/host key. No caller alias.
    target = {'ssh_alias': 'kat-ci', 'origin': plan['target']['origin']}
    pipeline.execute(receipt, archive, compose, target, plan, None, '', result,
                     ssh_config=ssh_config, ci_manifest=manifest, ci_bundle=bundle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'execute'))
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--target-scope', type=Path)
    parser.add_argument('--run-id', type=int)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--ssh-config', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        if not args.target_scope or not args.run_id or args.bundle or args.ssh_config or args.result:
            parser.error('Preparation requires public scope/run only')
        manifest = prepare(args.receipt, json.loads(args.target_scope.read_text()), args.run_id)
        with args.manifest.open('xb') as output:
            output.write(canonical(manifest))
    else:
        if not args.bundle or not args.ssh_config or not args.result or args.target_scope or args.run_id:
            parser.error('Execution requires the existing manifest/bundle/profile/result')
        execute(args.receipt, args.manifest, args.bundle, args.ssh_config, args.result)
