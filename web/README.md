# Reading Room frontend

- [Development, feature ownership, isolated checks and assets](../docs/frontend-development.md)
- [Using Kat](../docs/using-kat.md)
- [Synthetic validation](../docs/testing.md)
- [Documentation index](../docs/README.md)

Implementation lives in `src/app`, `src/features` and `src/shared`; browser suites
mirror those responsibilities under `tests/`. `web/dist` is generated served output,
not an isolated test destination or a substitute for preferred source.
