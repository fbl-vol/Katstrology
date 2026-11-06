# Appearance contracts

[Documentation index](README.md) · [Frontend development](frontend-development.md)

Kat provides eighteen reading palettes. Stored theme IDs and the
`kat.appearance.theme` preference key are compatibility contracts; unknown IDs or
inaccessible storage fall back to Reading Room before paint. Appearance affects
presentation, not archive content or chart calculations.

- `web/src/shared/themes.ts` owns IDs and descriptions.
- `web/src/shared/themes.css` owns explicit semantic screen/swatch tokens,
  including sidebar controls, focus, fields, links, warnings/errors and overlays.
- `web/index.html` contains the same prepaint allowlist. Any inline-script change
  requires updating its CSP hash in `m2/http_boundary/boundary.py`.

`web/tests/settings/theme-contract.spec.ts` guards all eighteen token blocks,
prepaint IDs, original token sets and retained default.
`web/tests/settings/appearance.spec.ts` checks contrast, persistence, keyboard use
and presentation-only behavior. Chart screen SVG/PNG use selected colors;
original standalone SVG stays light and print-ready SVG uses white paper.

Validate rendered desktop/mobile/short/ultrawide product screens, forms, notebook,
errors, focus and exports. Static palettes and passing token assertions do not
establish product visual acceptance. Use [isolated validation](testing.md), not a
running app, real account or served output.
