# Public-source and private-workspace boundary

## What belongs in Git

- Application code and schema migrations.
- Tests and fixtures authored with fictional/synthetic information.
- Reviewed configuration examples containing placeholders, not credentials.
- Product/setup/security documentation that stands alone without local plans.
- Deliberately selected UI source and assets, after checking embedded content.

## What stays local

Never commit local plans (`PLAN.md`), conversation transcripts (`session.txt`),
implementation/recovery checkpoints, review reports or working design folders.
They are not distribution artifacts. Write separate public product documentation
instead of changing those files into something publishable.

Keep all real birth records, chart documents, uploaded attachments, conversations,
personal notes, embeddings/search indexes, database snapshots, exports, model
caches, provider credentials and connection files out of Git as well. A chart can
identify someone even without their name. A reference filename or test input can
also disclose a private association.

The current prototype uses ignored `.local/` paths and an owned local PostgreSQL
fixture. This is not a claim that all private information lives in the database:
attachments, exports, deletion journals, models and backups are files too. A later
runtime-path change should put private state outside the checkout and preserve
existing recovery/deletion guarantees. Do not move live data or change runtime
paths solely to prepare a commit.

## Before committing

1. Stage explicit source paths, not the entire working folder.
2. Inspect `git diff --cached --name-status` and `git diff --cached`.
3. Check new docs, comments, examples and fixtures for real names, birth details,
   private excerpts, local account paths and embedded data. Use synthetic fixtures
   or optional externally supplied references; never publish a real fixture to
   make a test pass for another contributor.
4. Check configuration and generated outputs for credentials. Use a maintained
   secret scanner when available, but do not treat a clean result as proof that
   birth data or conversation content is absent.
5. Check dependency, ephemeris, model and source-content distribution terms before
   including any third-party material.

`.gitignore` prevents ordinary addition of matching untracked files. It does not
untrack existing files, erase earlier commits, prevent `git add -f`, or inspect
file content. To keep an already tracked private file on disk but stop future
tracking, use `git rm --cached -- <specific-path>` as part of a coordinated change.
Do not delete the working file or disrupt an active implementation/review owner.

## First public history

Local review history and public history are different boundaries. If local
commits contain checkpoints, private data or unreviewed working material, adding
ignore rules or a later removal commit does **not** make those commits safe to
push. An empty remote does not clean local history.

Preserve the local review checkout and its commit references. Once the intended
source revision is settled and audited, prepare a separate clean source snapshot
from explicitly approved paths and establish the public history there. Do not
copy the local `.git` directory, local plans or runtime directories into it.
Record the relationship to the local reviewed revision in local-only delivery
notes, and compare the exported source to that revision; disclose any differences
that were not reviewed. Do not invent a historical pre-implementation baseline.

Creating a safe source snapshot is preparation, not permission to publish it.
No push, force-push, repository visibility change, history rewrite or credential
rotation is implied by this document. If private material has already been
published, stop further publication and report the specific exposure; removing it
from the newest commit alone is not remediation.

## Existing history and future contributions

Before the first push, inspect the entire candidate history, including file paths
and historical blobs, not only the working tree. Re-run the audit after generated
files, rebases, merges or documentation changes. Avoid placing sensitive values
in commit messages, branches, tags, screenshots, issues or CI output.

Use CI secret scanning and branch protections when publication and repository
configuration are explicitly authorized. They supplement source review; neither
can reliably identify every piece of private narrative or birth information.
