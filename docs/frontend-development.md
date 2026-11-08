# Frontend development

[Documentation index](README.md) · [Using Kat](using-kat.md)

Reading Room is the supported conversation UI. It talks to the same-origin Python
server; it does not own the archive or provider credentials.

## Find the code

Paths in this table are relative to `web/`.

| Directory | Responsibility |
| --- | --- |
| `src/app/` | Session application, navigation and workspace composition |
| `src/features/conversation/` | Discovery, drafts, archive/event rendering, composer and scroll behavior |
| `src/features/people/` | Birth editor, people, personal details/links, Context collections, saved passages, timing and private records |
| `src/features/charts/` | Manual chart catalogue, technique forms, results, wheels and exports |
| `src/features/settings/` | Appearance, provider, personal-context consent and tone controls |
| `src/shared/` | API client, theme tokens/styles, brand assets and source notice |
| `tests/` | Matching capability suites; `support/` holds common fixtures/assertions |

`src/main.tsx` is the Vite mount entry; `vite-env.d.ts` supplies build types.
Do not add root compatibility re-exports for internal moves. Update callers.
`conversation/archive.ts` remains the sole turn sender/ACK/SSE owner. Workflow
coordinates drafts and navigation without duplicating transport or archived IDs.
Discovery captures refresh intent before asynchronous work: background completion
must not reset a newer search, pending older-page read or loaded history. Explicit
All conversations navigation is a separate action.

Global styles and assets live in `src/shared/`; chart and thinking styles stay
with their feature. Theme changes must preserve the synchronous CSP-hashed
prepaint bootstrap in `index.html`, all eighteen palettes and chart-export colors.

## Reading and result hierarchy

Use the shared text roles (`--text-reading`, `--text-support`, `--text-label`,
`--text-note`) rather than shrinking consequential text to fit a viewport.
Replies and retained passages need comfortable line spacing and a bounded measure;
long tables keep their own horizontal scroll. Wheel glyphs retain their calculation
geometry. Enlarged text must not change the document scroll owner or lose drafts.

Keep essential provisional, historical, unsupported, symbolic and clipping
qualifications beside the result. Put saved-history navigation after the principal
result, and numerical-method detail behind its existing disclosure where possible.
Necessary input controls and primary event/comparison tables remain directly
available. Opening a saved result always uses its immutable ID, never a newer chart.

Collection entries precede expansion and creation chrome. Counts must describe the
actual loaded/query result; refresh failure must not turn retained content into an
empty state. Keep independent searches, paging, edits and focus continuity.

Wheel formats share `WheelExportActions`: one native **Download chart** disclosure,
ordinary keyboard-reachable format buttons, Escape/focus return, and honest pending
or failure text. Do not add menu roles requiring arrow-key behavior to a disclosure.
Keep the existing SVG sanitization, palette policies, embedded fonts and captured
result provenance. A single CSV or JSON export stays a direct action.

## Phone navigation and retained-page continuity

`workspace-navigation.ts` is still the view authority. `browser-history.ts` journals
its visited routes for native Back/Forward; `NestedNavigation` lets person tabs,
library results and the existing natal reader participate in that same journey.
Explicit parent close removes that resource and its actual active reader descendant
atomically; the historical visit remains available to native Forward.
There is one popstate listener, not a second reader/router stack. Transient request
states, data refreshes and wheel highlights do not add visits. Explicit closing
can return to a matching ancestor; ordinary tab selection remains forward
navigation so a delayed pop cannot steal keyboard focus. Selecting a destination
from the mobile drawer replaces the drawer visit. No dummy root entries, global
Back/keyboard interception or programmatic PWA exit are added.

Browser history state contains only two opaque session/entry tokens. Resource IDs,
reading positions, source-return drafts and return intents stay in a session-local
RAM journal; no private draft/content/credential is placed in a URL, history state
or persistent store. Every native restoration validates the current authenticated
session. Changed destinations re-resolve people/conversations; library readers
fetch their immutable result again and do not display cached birth metadata before
that read succeeds. Deleted/unauthorized destinations fail closed; newer user
navigation supersedes an outstanding restoration. Logout/session change discards
the entire journal and component memory. Explicit sidebar person visits retain
existing fresh-reader behavior; native restoration can restore a visited reader.

Phone pointer/touch selection uses a non-modal `WheelPreview`, immediately after
the SVG and before notation/export. It reserves its measured layout space, uses
SVG coordinates and visual-viewport/header bounds, and never scrolls on selection.
At enlarged text sizes optional preview degree/member text yields to the complete
name and Read details action; complete facts remain in the existing reader.
Overlaps use a native select plus explicit selection. A concise heading/action and
bounded button padding keep the select, Select and Cancel controls in chart context
at 320px/200% text without reducing font size or hiding candidates. Measure each
post-touch and post-option state before activating the action; automation scrolling
an offscreen button is not evidence of unsolicited tap scrolling. Keyboard/directory activation
still enters the reader directly. The preview is outside the exported SVG.

On retained-page foreground/BFCache return, verify the session, then reconcile
saved conversation metadata and already loaded archive pages. Reconnect only the
existing archived turn/event cursor, never POST a message or start inference.
Queue and retry invalidate the foreground read's mutation lifetime, so a GET that
finishes after a newer ACK cannot merge stale paging/state or replace its stream.
Stream callbacks also check current connection ownership. Uncertain/pending
acknowledgements remain under the existing explicit same-ID retry contract. Preserve loaded pages, drafts and older-message position. The
composer uses visualViewport height/offset for its sticky inset and tall-editor
flow threshold, with safe-area padding; the document remains the scroll owner.

Focused checks live in `tests/navigation/pwa.spec.ts`,
`tests/continuity/pwa.spec.ts` and `tests/charts/exploration.spec.ts`. Keep existing
private-record, chart-return, archive paging, uncertain-ACK and provider-continuation
regressions in combined acceptance. Chromium visibility/viewport simulation is
not Android hardware Back, installed-PWA lifecycle or a real soft keyboard.
Actual device acceptance requires a separately permitted device path. Reload or
OS discard starts a fresh navigation/draft lifetime: no private offline cache,
service worker, automatic resend or persistent draft recovery is promised.

## Validate without touching a running app

From the repository root, with existing Python/Node/Chromium dependencies and
public inputs prepared as described in the backend guide:

```sh
# Plan first: prints the owned fixture and command sequence.
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile browser
# Execute only within the approved synthetic-validation scope.
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile browser --execute
# Focus by test title; capability directory moves do not change titles.
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile browser --execute --browser-grep 'pinned synthetic reading layout'
```

Use the runner rather than direct `npm run test:browser`: the raw Playwright
configuration defaults to port 8765. The runner owns a disposable database, free
loopback port, ignored build output and cleanup. It never substitutes the current
archive, live provider or served `web/dist`. Local and hosted runs both default to
Playwright's installed Chromium from the locked dependency version; no system
`/usr/bin/chromium-browser` is required. Native `PLAYWRIGHT_BROWSERS_PATH` can select
an existing Playwright cache. A missing browser fails rather than falling back.
To deliberately use another compatible installed Chromium, set `KAT_BROWSER_BIN`
to its absolute executable path on the runner command. The runner preserves only
that validated browser override from ambient `KAT_*`; missing, relative or
non-executable paths are refused, and fixture/provider settings remain isolated.
`npm --prefix web run test:browser:config` checks selection without starting a
browser, database or server.
Normal, fake-SIWC and fixed-clock suites have separate selectors. Test discovery
is recursive; keep the existing basename selectors in `playwright.config.ts` in
sync when adding tests. Screenshots and manifests remain under ignored `.local/`.

The public layout suite covers 1440×1024, 1920×1080, 2560×1080, 3440×1440,
390×844 and 390×560: general/selected-chart/long-turn scenes, geometry, navigation,
scroll and draft continuity. Inspect rendered output as well as assertions.
Public checks require no private mockup or historical Git object. The explicit
`--private-layout-reference` option is only for separately authorized access to
the pinned private reference; absent/changed inputs fail rather than silently
substituting a new baseline. Synthetic Chromium is not physical-phone,
virtual-keyboard, screen-reader, real-provider or human visual acceptance.

`tests/people/personal-context.spec.ts` exercises provider-free manual context,
section-owned multi-group paging/search, disclosure keyboard focus through loading
and failure, edit/removal, failure recovery, stable details, linking beyond the
sidebar's first 50 people (including duplicate names), and consent at desktop,
wide desktop, mobile, short mobile and tablet sizes. Its
renders are under `.local/personal-context/renders/`. Personal-context drafts and
navigation memory belong to the mounted workspace, not global/localStorage state.
The separate typed update capability reuses the existing archive sender and
continuation lifecycle; it must never be added to read-only `agent_reads` authority.

## Build or serve a separate instance

`npm ci --prefix web` installs locked dependencies; `npm --prefix web run build`
writes **served `web/dist`**. Those are preparation commands for your own new
instance, not isolated validation and not permission to overwrite an active
build. Follow the [backend guide](backend-development.md) for enrollment and serving, or
[deployment guide](../deploy/README.md) for immutable packaged operation.

`m2.web_server serve` supports explicit `--state-directory`, `--served-dist` and
`--port`. Defaults are checkout `.local`, `web/dist` and 8765. Do not copy private
state into a source tree. Store startup applies migrations; an existing archive
requires the authorized backup/preflight before activation, not an experimental
startup to see whether it works.

## Install assets and appearance

`public/manifest.webmanifest` defines stable same-origin `/` identity/start/scope.
There is no service worker or offline archive cache. Generate checked-in icons
from `src/shared/assets/kat-face.svg` with
`node web/scripts/generate-install-icons.mjs` (local Chromium, no network), then
inspect all three PNGs. Maskable artwork preserves central safe-circle padding;
regressions check dimensions, bytes and MIME types.

The static manifest uses Reading Room paper; page `theme-color` follows the
selected palette. Browser/OS chrome, gesture areas, native splash, WebAPK install
and real session persistence require physical-device verification. Theme choice
uses localStorage with a safe default; it changes no chart, consent, message or
archive record. Screen wheels follow the palette, original SVG retains a light
fallback, PNG follows the screen and print SVG is explicitly light. Bundled WOFF
fonts load same-origin; detached exports embed their own subset fonts. Preserve
[font notices](../THIRD-PARTY-NOTICES.md) when moving assets.
