# Katstrology

Kat is a conversation-centred astrology workspace: a durable private archive,
reproducible chart calculations, attributed references and a same-origin Reading
Room UI. Python/PostgreSQL own the archive; Preact renders the browser client.
Both standalone local operation and packaged HTTPS deployment are supported.

Start with the **[documentation index](docs/README.md)** for using Kat,
development, testing, deployment and recovery.

## Boundaries

Calculated astronomical facts, sourced interpretations, user reports and model
synthesis are distinct. Accurate positions do not scientifically validate
astrological interpretations, verify birth details or establish response quality.

The optional ChatGPT-plan connection is default-off and requires explicit account
permission. Sending selected context to a hosted model is not local-only
processing. Synthetic tests establish neither live-provider eligibility nor
physical-device or private-data acceptance. The small local model is a test
fixture, not a validated conversational astrologer.

This repository contains source, migrations, public metadata and synthetic tests,
not conversations, birth records, credentials, backups or private working notes.
Runtime state belongs outside an immutable deployed source tree. See
[publication boundaries](docs/PUBLICATION.md) before staging or sharing files.

## License

Original code is [GNU AGPLv3 only](LICENSE) (`AGPL-3.0-only`), without warranty.
The repository is the preferred source; generated `web/dist` is not a substitute.
[Third-party notices](THIRD-PARTY-NOTICES.md) cover fonts, GeoNames and dependency
obligations. Swiss Ephemeris data, model weights and third-party text corpora are
not bundled. Public source does not itself authorize deployment, private-data
access or provider use.
