# Third-party data, fonts and dependencies

The [AGPL-3.0-only license](LICENSE) covers original application code, **not** these separately licensed materials. Preserve their notices when copying, modifying or distributing them. This inventory describes the checked-in source snapshot; it is not a legal compatibility opinion or a promise that separately installed dependencies may be redistributed without reviewing their licenses.

## Offline place data

`m2/data/geonames-cities5000.zip`, `geonames-admin1.txt` and `geonames-countries.txt` are a 2026-10-29 snapshot of [GeoNames](https://www.geonames.org/) `cities5000.zip`, `admin1CodesASCII.txt` and `countryInfo.txt`. Data © GeoNames, [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). The two plain-text filenames were shortened in this repository. See [`m2/data/README.md`](m2/data/README.md) for upstream links, hashes, coverage and accuracy limits. These are city-centre references, **not** verified individual birth locations.

## Open astronomy text excerpt

`m2/data/openstax-seasons-excerpt.txt` is one verbatim text paragraph from OpenStax
contributors, *Astronomy*, section 4.2, [The Seasons](https://openstax.org/books/astronomy/pages/4-2-the-seasons),
accessed 2026-11-01. The [edition preface](https://openstax.org/books/astronomy/pages/preface)
grants [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) with attribution to
OpenStax and the contributors. The manifest alongside the excerpt records the
processing and location. No figures or full book are included. Reproduce this
notice/attribution and identify changes if adapting it; the application's AGPL
license does not relicense this excerpt. Astronomy facts are not astrological
interpretive endorsement.

## Bundled font subsets

`web/src/shared/assets/kat-astro-forms.woff` and `kat-astro-sun.woff` are subsets of Noto Sans Symbols and Noto Sans Symbols 2 respectively. Copyright 2022 The Noto Project Authors (https://github.com/notofonts/symbols). The font software remains under the [SIL Open Font License 1.1](web/src/shared/assets/OFL-Noto.txt); the original font project and its preferred sources are at [notofonts/symbols](https://github.com/notofonts/symbols). Subsetting/WOFF conversion changes the font files, not their license.

## Packaged public CPU embedding model

The release image includes only the five checksum-pinned files of
[Qdrant/bge-small-en-v1.5-onnx-Q](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q)
at revision `aa8f8b060edb00e03bfdd08813a2949946c8ba55`, a quantized
ONNX port of [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5).
Both upstream model cards declare MIT; the upstream FlagEmbedding licence text
and copyright notice are preserved in [`m2/public-model-LICENSE.txt`](m2/public-model-LICENSE.txt)
and copied into the image. `m2/references/public_model.py` identifies every shipped file,
its SHA-256, size and the exact public revision. Weights are not checked into Git,
and the builder cannot include unrelated Hugging Face cache files, private books,
vector indexes or credentials. Model scores are retrieval hints, not citation
support or verified multilingual quality.

## Installed software

- The browser dependencies are declared in [`web/package.json`](web/package.json), with exact resolved versions and reported package licenses in [`web/package-lock.json`](web/package-lock.json). They are installed with `npm ci` rather than vendored here. The locked JavaScript packages report MIT, ISC, BSD-3-Clause or Apache-2.0 licenses; retain their individual notices when distributing a built bundle.
- Backend and optional local-probe dependencies are specified in [`m2/requirements.txt`](m2/requirements.txt), [`probes/requirements-swiss.txt`](probes/requirements-swiss.txt) and [`probes/requirements-model.txt`](probes/requirements-model.txt). These files are package declarations, not license grants. Review the installed packages' own terms before redistributing binaries or running a public service.
- [Swiss Ephemeris](https://www.astro.com/swisseph/swisseph.htm) and its Python wrapper are separately installed. Swiss ephemeris data files are **not bundled** here; they are supplied locally for numerical tests and must not be inferred from the GeoNames data. Consult the [Swiss Ephemeris licensing information](https://www.astro.com/swisseph/sweph_g.htm) and [natal calculation contract](docs/natal-charts.md) before distributing or serving a Swiss-backed build.
- No third-party interpretive texts, private research notes, model weights, provider credentials or individual birth records are checked in. Other reading links in `docs/reference-sources.md` are research pointers, not an included text corpus.

For the application's preferred build/run instructions see [documentation index](docs/README.md), [backend development](docs/backend-development.md) and [frontend development](docs/frontend-development.md). A built `web/dist` alone is not the corresponding source.
