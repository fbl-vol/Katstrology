# Katstrology

A local-first, conversation-centred astrology workspace in development. The goal
is an astrologically literate companion supported by reproducible calculations,
attributed references and selective recall of past conversations.

## Current implementation

The local Python/PostgreSQL application provides a durable conversation archive,
source-labelled retrieval, CLI and MCP tools, and a same-origin
[Reading Room browser UI](web/README.md). Legacy tropical Sun-only calculations
and bounded solar events remain available. A
[versioned Western tropical natal chart](m2/NATAL-CHART.md) uses explicitly
supplied birth inputs for planetary and node positions, aspects and qualified
houses/angles. The manual chart catalogue also offers two-person synastry and
[separately qualified return, progression, timing and relationship calculations](m2/ADVANCED-TECHNIQUES.md).
These are neither birth-time rectification nor a validated interpretive engine.
The small optional local model is a synthetic-test fixture, not a validated
conversational astrologer; hosted-only startup does not require it.

The browser's optional **Sign in with ChatGPT** plan adapter is implemented but
default-off. Agent checks of account authorization and direct Responses inference
use synthetic provider fixtures; browser upload ingress is closed while older
file-backed turns retain their archived consent and replay semantics. The user
reports successful live conversations; this is not independent verification of
provider eligibility, live inference or reading quality. A sign-in alone does not
grant plan inference permission, and selected data sent to a hosted model is not
local-only processing. No production deployment or real-data import is approved;
Swiss Ephemeris and third-party content terms, plus private-data/provider policy,
remain separate release obligations.

See [the local prototype guide](m2/README.md) and
[architecture overview](docs/architecture/README.md) for setup, supported
boundaries, synthetic walkthroughs and recovery behaviour. Some historical
feasibility checks require private local reference material and are not
reproducible from public source alone; they must not be treated as public-fixture
validation.

## Public code, private workspace

This repository is for application source, migrations, synthetic tests and
sanitized product documentation. It is **not** a home for birth records, chart
uploads, conversations, personal memories, tokens, backups or exported data.

Local planning documents, transcripts, implementation checkpoints, review notes
and design explorations are not product documentation and stay out of Git.
`PLAN.md` and `session.txt` are local-only files, even if they have no obviously
sensitive content. Create separate public documentation rather than publishing
sanitized versions of those working files.

The current prototype stores private/generated files in ignored `.local/` paths
and conversations in its owned PostgreSQL fixture. Ignoring a path is an accident
prevention measure, not a security or archival boundary. Future production runtime
storage should be outside the source checkout; that relocation is not implemented
by this repository policy.

See [publication rules](docs/PUBLICATION.md) before staging or publishing anything.
Do not use real private content in tests, screenshots, examples or issue reports.

## Limitations and licensing

Accurate astronomical calculations do not scientifically validate astrological
interpretations. This project must distinguish calculated facts, sourced
interpretations, user reports and creative synthesis.

Original application code is licensed under [GNU AGPLv3 only](LICENSE)
(`AGPL-3.0-only`); no warranty is provided. The preferred source is this
repository: `m2/` contains the server, calculation code and migrations;
`web/src/` contains the browser source; `web/package.json` and
`web/package-lock.json` pin its build inputs. See [backend setup](m2/README.md),
[browser build instructions](web/README.md), and [third-party notices](THIRD-PARTY-NOTICES.md).
`web/dist` is generated output, not a substitute for the corresponding source.

The project license does not relicense separately attributed fonts, GeoNames
place data or installed dependencies. Swiss Ephemeris and its Python wrapper
have their own license obligations; the Swiss ephemeris data files, model weights
and third-party text corpora are not included in this source snapshot. Public
repository visibility does not itself authorize deployment, provider access or
use of private data.
