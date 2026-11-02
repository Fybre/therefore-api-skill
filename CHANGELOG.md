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
- Corrected `GetObjects` permission-mask defaults and `ExecuteTaskInfoQuery` required members
  after live validation against Web API 35.0.3.0.
- Removed the incorrect generic `GetCategoryInfo.FieldType` mapping.
- Corrected LogMask (key 700) values: `1` = Log always and `3` = Log failure (were swapped); added
  the 52-slot event map and key 701 archive-mode values from Solution Designer 35.0.3.
- Reference client claim/disclaim/delegate now send `InstanceNo`/`TokenNo` (delegate also
  `UserName`/`DomainName`) instead of the non-existent `WorkflowInstanceToken`.
- Full-text examples and the reference client default to `SearchScope: 2` (index data and
  document content); `0` searched index data only.

### Added

- Workflows section (inbox `WorkflowFlags`, instance fields, claim/finish/delegate/link, comments
  on instances, process names, out of office), `GetObjectsList`, document downloads/thumbnails/
  quick saves/shared links/Web Client URLs, JWT renewal and `GetConnectionToken`, SSO discovery,
  top-level `FullText` in category queries, and **Workflow Notifications (Webhooks)** with the
  eight event types and `ExpiryOption` semantics; pitfalls #43–#49 and the official 2026 docs.
- Reference client: `finish_current_workflow_task`, `link_document_to_workflow`, and a
  `search_scope` parameter for `execute_full_text_query`.
- 20 operation contracts from Web API 35.0.3.18 with a redacted fixture and tests.

- On-prem SQL schema reference (`references/database_schema.md`) derived from a full SSMS script
  of an on-prem Therefore database: table naming (`TheCat{n}`, `TheCase{n}`, `TheIxTable{n}`,
  `TheKeywords{n}`), `TheString` name lookups, workflow/settings/audit/integration tables,
  sensitive-column list and read-only starter queries; new **On-Premises SQL Database** section
  and pitfalls #40–#42.
- Server settings operations (`GetSettings`, `GetGlobalSettings`, `GetSettingString`,
  `GetSettingInt`) with live-verified shapes, error behaviour, and the Server Logging keys
  700–704 (log mask, archive mode/weekday/time, split size); pitfall #39.
- Machine-readable operation contracts and fixture-based regression tests.
- Read-only smoke-test script and CI validation.
- Project README and contribution guidance.
- Redacted craigdemo read/write validation evidence with verified cleanup.
