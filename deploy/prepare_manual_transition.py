"""Prepare an offline, hash-pinned manual transition installation handoff.

No server access or installer execution. The existing manual target, signer and
schema23 baseline are preserved; only its explicit23→24 allowlist is added.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess

from deploy import release_pipeline as pipeline

ROOT = pipeline.ROOT
OLD_HELPERS = {
    'release_access.py': 'cd3378cec497f721824f9a35f7d03955839204ee3aa1a55f8a28072f00686777',
    'release_remote.py': '870b58183cf147ee799f65ecac114ba5fa9432470b85f65c12ac48a3d682621b',
}
LANE = {'from': 23, 'to': 24, 'migrations': {
    '024_account_tones.sql': '523775c5caa77b398d2f8804711f12029a7c810031f66ad4505003486feb8a71'},
    'added_tables': ['account_tones'], 'added_columns': {}}


def prepare(receipt_path, old_receipt_path, policy_hash, old_image, output):
    candidate, _, compose, schema = pipeline.artifact(receipt_path)
    old, _, old_compose, old_schema = pipeline.artifact(old_receipt_path)
    from deploy.release_access import HEX, IMAGE
    if (not HEX.fullmatch(policy_hash) or not IMAGE.fullmatch(old_image)
            or old_image not in (old['image_id'], old['config_digest'])
            or (old_schema, schema) != (23, 24) or old_compose != compose
            or old['commit'] != '094be931c8d5bde3689086fa8daa232c70c9becb'
            or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()
            or candidate['commit'] != subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()):
        raise ValueError('Exact clean candidate, retained094 and current protected pins required')
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in ('release_access.py', 'release_remote.py', 'release_pipeline.py'):
        body = (ROOT / 'deploy' / name).read_bytes()
        (output / name).write_bytes(body)
        hashes[name] = sha256(body).hexdigest()
    manifest = {'contract': 1, 'candidate_commit': candidate['commit'], 'candidate_tree': candidate['tree'],
        'artifact_sha256': candidate['image_archive_sha256'], 'expected_policy_sha256': policy_hash,
        'expected_old_helpers': OLD_HELPERS, 'new_helpers': hashes,
        'compose_sha256': sha256(compose).hexdigest(), 'manual_transition_lane': LANE,
        'writes': 'three adjacent protected helpers and manual_transitions only; no app/DB/CI/key changes'}
    (output / 'install-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    draft = {'lane': LANE, 'old_image': old_image, 'old_source_sha256': old['source_offer_sha256'],
             'settled_existing_work': False}
    (output / 'manual-transition-DRAFT.json').write_text(json.dumps(draft, indent=2) + '\n')
    shutil.copyfile(ROOT / 'deploy/install_manual_transition.py', output / 'install_manual_transition.py')
    manifest_hash = pipeline.digest(output / 'install-manifest.json')
    (output / 'INSTALL.md').write_text(f'''# Non-executing manual transition handoff

Candidate: `{candidate['commit']}` / tree `{candidate['tree']}`.
Manifest SHA256: `{manifest_hash}`.
Installer SHA256: `{pipeline.digest(output / 'install_manual_transition.py')}`.

Nothing has been installed, signed or released. A flag is not user approval.
The root installation and fresh signed release belong to the separately scoped
execution instruction. Do not use CI admission or the historical094 signature.

1. Verify these handoff pins after transfer through the user-provided root channel.
   Discover the existing protected helper directory; do not guess a Compose path.
   From that directory's parent, run this bundled installer with `--manifest-sha256
   {manifest_hash}` and `--helper-directory ACTUAL_DIRECTORY`. Default is plan only.
   `--execute` is restricted to explicit root-install approval. It checks exact old
   access/helper/policy pins and the shared idle release lock, retains originals,
   and adds only the exact lane. Schema baseline remains23; signer/target/key and
   installed Compose are unchanged. Never rerun an ambiguous/partial installation.
2. Confirm the actual old image/source/schema still match094 and the old owner is
   settled.094 has no drain socket: maintain the signed settled-work condition
   through its stop. Do not pretend the old app was mechanically drained. If work
   cannot be settled/kept settled, stop; this direct lane is not admissible.
3. Only then change `manual-transition-DRAFT.json` settled_existing_work to true.
   Prepare a new attempt with this candidate's `deploy.release_pipeline
   --prepare-dir NEW_PRIVATE_DIRECTORY` and `--manual-transition` file, the
   existing exact target and candidate receipt.
   The immutable a0 receipt is NOT the new controller's candidate receipt.
4. Obtain a fresh attempt/plan-bound signature from the same pinned human signer.
   Execute only through the existing signed manual forced command. No SQL/root
   migration, schema-number bump, bootstrap or fabricated CI witness is involved.
5. Any ambiguous migration/start/reopen is stop-only. Keep the attempt, fence,
   snapshots and source evidence. Never restart old094 against24 or restore its
   backup over current data. Old23/new24 restore tests are empty-target recovery
   evidence, not authorization for live rollback. After reopening, an uncertain
   completion record must not kill newly admitted work or trigger a resend.

Public TLS/Caddy, installed root protection and live assets must be checked during
that actual release; synthetic native evidence does not claim these observations.
CI enrollment and unattended delivery remain unfinished. After direct24, the
schema23-only bootstrap is not applicable; do not downgrade to reuse it.
''')
    return {'status': 'prepared-not-executed', 'directory': str(output), 'manifest_sha256': manifest_hash,
            'installer_sha256': pipeline.digest(output / 'install_manual_transition.py'), **hashes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--old-receipt', type=Path, required=True)
    parser.add_argument('--installed-policy-sha256', required=True)
    parser.add_argument('--old-runtime-image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.receipt, args.old_receipt, args.installed_policy_sha256,
                             args.old_runtime_image, args.output)))
