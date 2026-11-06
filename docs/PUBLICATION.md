# Public source and private state

[Documentation index](README.md)

## Repository contents

Track application/build source, migrations, authored synthetic tests, reviewed
placeholder configuration, current product documentation and licensed public
assets. Keep real birth records, chart documents, conversations, notes, private
reference excerpts, embeddings/indexes, database snapshots, exports, model caches,
provider credentials and connection files out of Git. A chart or filename can
identify a person or private association without containing a name.

Local `PLAN.md`, transcripts, checkpoints, review reports and working design
folders are not product documentation. Keep them local; do not sanitize and publish
those working records as a substitute for a standalone reader guide.

Development uses ignored `.local/` outputs; packaged runtime state uses explicit
external paths. Attachments, credentials, exports and deletion journals are files
too, not all PostgreSQL content. Source packaging must never copy a runtime state
directory, even if it is ignored. Do not move live state merely to prepare a commit.

## Before committing or publishing

1. Stage explicit source paths and inspect the staged name/status and full diff.
2. Inspect docs, comments, fixtures and generated assets for real names, birth
   details, private excerpts, account paths and embedded data. Use authored
   synthetic cases, not a real fixture published to make a test reproducible.
3. Use the available secret scanner, but do not treat a clean scan as proof that
   private narrative, charts or conversation content are absent.
4. Check dependency, ephemeris, font/model and source-content distribution terms.
   Keep required attribution and preferred source/build inputs together.
5. Audit the history that will be published, not only its current tree. Repeat
   after generated files, merges, rebases or documentation changes. Commit messages,
   branches, tags, screenshots, issues and CI logs can disclose private material too.

`.gitignore` prevents ordinary addition of matching untracked files; it does not
untrack files, erase history or inspect content. Removing a tracked private file
from the latest tree does not make older commits safe. Preserve local review
references when preparing a separately audited clean source snapshot; never copy
a private `.git` directory or working/runtime material into it. Record source
identity and disclose differences rather than inventing historical evidence.

If private material has already been published, stop further publication and
identify the exposure; a removal commit alone is not remediation. Publication,
visibility/history changes and credential rotation are separate consequential
actions, not implied by documentation cleanup.

## Corresponding source

An immutable release pairs the application image with its exact preferred source
offer and build inputs. `web/dist` alone is not corresponding source. Public
visibility neither relicenses third-party content nor authorizes private-data or
provider use. See [license](../LICENSE), [third-party notices](../THIRD-PARTY-NOTICES.md)
and [deployment](../deploy/README.md).
