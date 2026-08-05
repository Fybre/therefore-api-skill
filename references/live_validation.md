# Live validation log

## Craigdemo — 2026-08-05

Environment: Therefore Web API 1.0, service version 35.0.3.0, Basic authentication with a
`TenantName` header. No credentials, user names, document content, or index values are stored.
Machine-readable results are in `tests/fixtures/live_craigdemo_2026-08-05.json`.

### Read results

- Authentication, category tree, category metadata, async pagination/release, document index
  data, history, checkout status, comments, users, keyword lookup, and stream download passed.
- Craigdemo exposed 204 categories and 11 case definitions to this login.
- On a category with more than 500 documents, omitted `MaxRows` returned 500, `MaxRows: 0`
  returned 500, and `MaxRows: 501` returned 501. Thus `0` is not unlimited on 35.0.3.0.
- A 793,977-byte existing stream downloaded successfully. The fixture records only size and
  SHA-256, not content or file metadata.
- `GetObjects {"Flags": 0, "Type": 11}` returned 32 items. Adding
  `RoleAccessMask: 18446744073709551615` returned zero, so the client no longer adds that mask
  by default.
- `ExecuteTaskInfoQuery {}` failed because `QueryMode` and `ViewMode` are required. Supplying
  `QueryMode`, `ViewMode`, and `MaxRows` succeeded with the `QueryResult` response root.
- Full-text search executed successfully but the chosen term returned zero results in category
  56; this does not prove that category's files are indexed.

### Disposable document results

Category 56 (`Test Category`) was used for an isolated test document.

- Category-default auto-append mode (`WithAutoAppendMode: 0`) failed before creation because
  the category's configured auto-append field was invalid.
- Explicit mode `4` (`No check`) created the document successfully.
- Index-data read-back, exact query read-back, byte-for-byte stream download, comment add/edit,
  index update, checkout/undo, deletion, and post-delete verification all passed.
- Document 22161 was created by the test and confirmed deleted afterward.

### Disposable case results

Case definition 11 (`Referenced Case Test`) was used.

- Create, read, history, close, reopen, delete, restore, and final deletion all passed.
- `SaveCaseIndexDataQuick` returned a generic `ServerError` for partial and full-state payloads.
  `SaveCaseIndexData` with creation timestamps also returned `ServerError`.
- A case-document link was not attempted because disposable document creation in the linked
  category failed before a case or link was created. Existing documents were not modified.
- Cases 96–99 were created by these tests and confirmed unavailable after cleanup.

### Safety and cleanup

Every successful write targeted an object created by the same validation run. All created
documents and cases were deleted, and post-cleanup reads returned deleted/unavailable errors.
No existing tenant object was updated, linked, deleted, or checked out.
