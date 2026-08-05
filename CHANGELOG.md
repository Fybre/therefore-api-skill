# Changelog

## Unreleased

### Fixed

- Corrected wildcard examples to use `*` instead of SQL `%`.
- Updated full-text search examples to the live `Search`/`Categories` request and flat
  `Results` response.
- Corrected stream downloads to treat `FileData` as a byte array.
- Corrected comments, case creation, user listing, and workflow completion payloads.
- Canonicalized `CreateDocument` as a top-level request payload.
- Fixed nested multi-query result merging and safe tenant-host detection.
- Preserved structured Therefore `WSError` details in `ThereforeAPIError`.

### Added

- Machine-readable operation contracts and fixture-based regression tests.
- Read-only smoke-test script and CI validation.
- Project README and contribution guidance.
