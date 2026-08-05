# Therefore API skill function audit

Audit date: 2026-08-05  
Audited commit: `b28b70711e9c73f53867c3862a98228bfd5306ad` (`main`, identical to `origin/main`)  
Repository: <https://github.com/Fybre/therefore-api-skill>

## Executive summary

The skill contains valuable live-tested knowledge, especially around tenant headers, query
conditions, async pagination, category-tree shape, comments, cases, and full-text search.
However, it is not yet safe to treat every included example or helper as executable reference
code. The highest-risk problem is internal drift: later corrections were added to `SKILL.md`
and parts of `references/api_endpoints.md`, but older contradictory examples remain elsewhere.

The initial audit found:

- **6 high-priority correctness defects** in examples or the bundled Python client.
- **7 medium-priority contract conflicts** that need a live request/WSDL test before one shape
  is declared canonical.
- **Broad coverage gaps**: several endpoint families named by the client or MCP section have no
  local request/response documentation or runnable example.
- **No automated tests, schema fixtures, CI, README, licence, or release/version policy.**
- The GitHub repository has **no open or closed issues**, so the known gaps currently exist only
  in prose and are not trackable as work items.
- `references/therefore_client.py` is a stale copy of `therefore-mcp`: the local file is 1,058
  lines while the current upstream file is 1,822 lines and includes newer auth/configuration
  behaviour. The skill called the local file the "full implementation", which was no longer true.

## Remediation status

The repository was remediated on 2026-08-05. Confirmed defects F-01 through F-06 and static
contract conflicts F-07 through F-13 are fixed and covered by local regression tests. The
generated REST operation catalogue at `therefore-mcp` commit
`f32d54f489c73f12025ad19bb03a5be017f49a6a` was used to resolve HTTP verbs,
`CreateDocument`, `CompleteTask`, comments, cases, and stream schemas.

| Findings | Status | Result |
|---|---|---|
| F-01–F-06 | Resolved | Corrected examples and wrapper payloads; added regression coverage. |
| F-07–F-10 | Resolved | Documented GET exceptions, canonicalized document/task contracts, and fixed nested multi-query merging. |
| F-11 | Documentation resolved; live matrix pending | All local guidance now treats `0` as the 500-row default and uses `2147483647` explicitly for all rows. |
| F-12–F-13 | Resolved | Safe hostname matching, pinned upstream references, focused-client ownership note, and structured `ThereforeAPIError`. |
| F-14–F-15 | Resolved | Replaced placeholders, removed the fake asset, and added contract fixtures, 17 unit tests, and CI. |
| F-16 | Partially resolved | Added README, contribution guide, and changelog. Licence selection and an initial release/tag require owner decisions. |
| F-17–F-18 | Partially resolved | Added a machine-readable contract registry and redacted synthetic fixtures. Live fixtures still need server/version metadata. |
| F-19 | Resolved | Local references are local paths; external references are pinned to commits. |
| F-20 | Deferred | The skill remains long; splitting MCP/Formio material is a maintainability improvement, not a correctness blocker. |

The remaining work requires a disposable live tenant or repository-owner decisions; it is
listed under "Remaining live verification" below.

## Confidence labels

- **Confirmed defect**: contradicted by another section explicitly described as live-verified,
  or mechanically wrong for the documented response type.
- **Contract conflict**: two repository sources disagree, but this audit did not make a live
  tenant mutation to decide which contract is accepted by the server.
- **Coverage gap**: the operation is mentioned or wrapped, but lacks enough local material to
  implement and verify it safely.

No live tenant calls were made during this audit. Destructive and state-changing functions must
be verified in a disposable category/case/user environment.

## Original findings and remediation rationale

### P0/P1: fix before relying on generated code

| ID | Area | Finding | Evidence | Required action |
|---|---|---|---|---|
| F-01 | Query wildcard | Two examples use SQL `%`, which the skill says silently returns zero rows. | `references/api_endpoints.md:223`, `references/python_examples.md:312`; contradicted by `SKILL.md:88-104` and pitfall 17. | Replace both with `LIKE Acme*`; add a consistency test that rejects `%` in `LIKE` examples. |
| F-02 | Full-text search | The Python helper uses obsolete `SearchText`/`CategoryNo` fields and parses a nonexistent `QueryResult` wrapper. It will either 500 or return an empty list. | `references/python_examples.md:1187-1249`; corrected contract at `references/api_endpoints.md:765-835` and `SKILL.md:797-811`. | Rewrite the helper to send all required fields and return the flat `Results` array. Add a fixture test. |
| F-03 | Stream download | The Python helper base64-decodes `FileData`, although the live-verified docs say it is a JSON byte array. It also says stream metadata comes from `GetDocumentIndexData`, while the endpoint reference says `GetDocument`. | `references/python_examples.md:781-818`; corrected contract at `references/api_endpoints.md:593-619` and `SKILL.md:715-721`. | Use `bytes(result["FileData"])`; optionally support `FileDataBase64JSON` only when explicitly requested; correct stream discovery guidance. |
| F-04 | Cases | The bundled client sends `CaseDefinitionNo` to `CreateCase`, while the live-verified reference says `CreateCase` requires `CaseDefNo`. | `references/therefore_client.py:373-377`; `references/api_endpoints.md:1072-1088`; `SKILL.md:422-424,778-781`. | Change the wrapper payload to `CaseDefNo` and add a non-destructive request-shape unit test. |
| F-05 | Comments | The bundled client sends `DocNo`/`VersionNo` for `AddComment` and `LoadComments`. The live-verified contract requires `ObjNo`, `ObjType: 2`, and `MaxCount` for loading. | `references/therefore_client.py:341-345`; `references/api_endpoints.md:709-762`; `SKILL.md:419-421,762-765`. | Correct both wrapper methods, expose `max_count`, add `edit_comment`, and test payload snapshots. |
| F-06 | Users | `execute_users_query` requires a query string and defaults to `Flags=5`; the verified list-all pattern is no query and `Flags=4`, while the skill notes a query plus flags can return an empty list. | `references/therefore_client.py:495-500`; `references/api_endpoints.md:839-869`; `SKILL.md:432-447,742-746`. | Make `query` optional and default `flags=4`; add fixtures for regular and AD/LDAP users. |

### P1/P2: resolve conflicting contracts

| ID | Area | Conflict / risk | Evidence | Next step |
|---|---|---|---|---|
| F-07 | HTTP verbs | The skill says every operation is POST and no GET endpoints exist, but its bundled client uses GET for `GetSystemCustomerId` and auto-routes five more operations to GET. `call_endpoint("GetDocumentStream", payload)` also discards the payload. | `SKILL.md:21-24,679-682`; `references/therefore_client.py:166-196,474-475,710-721`. | Derive the verb per operation from WSDL/live traffic, publish an exception table, and remove unsafe auto-detection. |
| F-08 | CreateDocument | `SKILL.md`, endpoint reference, and raw Python example wrap the payload in `TheDocument`; the bundled client sends the document fields flat. | `SKILL.md:352-370`; `references/api_endpoints.md:519-556`; `references/python_examples.md:352-411`; `references/therefore_client.py:310-318`. | Run both payloads in a disposable category, record server version, retain only the accepted canonical shape (or document version-specific variants). |
| F-09 | CompleteTask | The endpoint reference uses `TaskNo`/`SelectedExitNo`/`Comment`; the bundled client uses `WorkflowInstanceToken`/`TaskNo`/`UserDecision`. | `references/api_endpoints.md:1000-1017`; `references/python_examples.md:972-1037`; `references/therefore_client.py:347-353`. | Inspect WSDL data members and test both workflow modes; split methods if they represent different task APIs. |
| F-10 | Multi-query parsing | The documented response nests each result under `QueryResults[].QueryResult`; `execute_async_multi_query_all` merges `ResultRows` and category identifiers from the outer object. It can report zero rows even when results exist. | `references/api_endpoints.md:302-365`; `references/therefore_client.py:744-792`. | Capture real first/next-page fixtures and correct the merger; until then, deprecate the all-pages helper and recommend single-category async queries. |
| F-11 | MaxRows | `MaxRows: 0` is documented as a 500-row default in the core docs but as unlimited in PowerShell. | `SKILL.md:146`; `references/api_endpoints.md:215`; `references/powershell_reference.md:95`. | Test `0`, omitted, `500`, and `2147483647` on a category with >500 rows; document server-version behaviour in one canonical table. |
| F-12 | Authentication/tenant detection | Minimal Python examples test hostname membership with `in`, whereas current upstream code uses a proper `.thereforeonline.com` suffix check and supports additional S2S configuration absent locally. | `SKILL.md:54-65`; `references/python_examples.md:13-48`; local/upstream `therefore_client.py` diff. | Use parsed-host exact/suffix matching everywhere; either sync the upstream client automatically or replace the local copy with a pinned link/version. |
| F-13 | Error model | The error reference shows nested `WSError`, while the bundled client's exception parser only looks for top-level `Message`, `message`, or `error`, then raises a reconstructed `HTTPError`. Callers cannot reliably inspect Therefore error codes. | `references/api_endpoints.md:1181-1218`; `references/therefore_client.py:95-164`. | Add a typed `ThereforeAPIError` preserving status, endpoint, `WSError`, error ID, and response body; test 400/401/500 fixtures. |

### P2: repository and maintainability gaps

| ID | Finding | Impact | Next step |
|---|---|---|---|
| F-14 | `scripts/example.py` and `assets/example_asset.txt` are untouched scaffold placeholders. | They add no Therefore capability and make the package look unfinished. | Replace the script with a read-only connection/category/query smoke test; remove the asset directory unless a real fixture is needed. |
| F-15 | No tests or CI. | Regressions such as `%`, obsolete full-text fields, and response-shape drift survive documentation updates. | Add `pytest` payload/fixture tests, Markdown consistency checks, link checks, and GitHub Actions. |
| F-16 | No README, licence, contributing guide, changelog, or release tags/version. | Installation, compatibility, provenance, and reuse terms are unclear. | Add minimal project metadata and a server-version/last-verified matrix. |
| F-17 | Corrections are duplicated across `SKILL.md`, endpoint docs, Python docs, PowerShell docs, the local client, and `therefore-mcp` knowledge. | A correction in one place leaves dangerous stale examples elsewhere. | Define one source of truth (machine-readable operation registry/fixtures) and generate or lint the repeated tables/examples. |
| F-18 | Date-stamped live findings have no test transcript, tenant/server version, request ID, or redacted fixture. | Future maintainers cannot distinguish universal API behaviour from tenant/version-specific behaviour. | Store redacted request/response fixtures with `verified_on`, Web API/server version, auth mode, and expected result. |
| F-19 | Extended references point at unpinned `main` branches in three repositories. | Behaviour can change without this skill commit changing; local snapshots can silently diverge. | Pin production references to commits or release tags and use an automated dependency-update PR. |
| F-20 | `SKILL.md` is 827 lines and includes detailed MCP product documentation alongside REST guidance. | Higher context cost and mixed responsibilities make routing and maintenance harder. | Keep critical invariants/workflows in `SKILL.md`; move operation details into routed references and split MCP/Formio integration guides. |

## Function-by-function coverage

Legend: **usable** = internally consistent enough for read-only use; **conflict** = contradictory
payload/response guidance; **partial** = mentioned but missing important schema, example, or
verification; **gap** = name only or absent.

| Function / family | Status | What is documented | Gap or issue | Recommended next verification |
|---|---|---|---|---|
| `GetConnectionToken` / Basic / Bearer | Partial | URL, headers, token response | Bearer bootstrap/expiry and auth failure fixtures absent; S2S upstream drift | Test Basic→token→Bearer and token expiry on cloud/on-prem |
| `GetDomainInfo`, version/discovery/system calls | Partial | `GetDomainInfo` stub; several wrappers | Verb conflict; most responses undocumented | WSDL verb/schema inventory plus read-only fixtures |
| `GetCategoriesTree` | Usable | Correct `TreeItems`/`ChildItems`/`ItemType` shape | No reusable flattening helper/test | Add recursive helper and mixed-node fixture |
| `GetCategoryInfo` | Usable | Request, response, field types | Table-field definitions, dependent fields, access masks lightly covered | Fixture for every field type and conditional metadata |
| `ExecuteSingleQuery` | Partial | Core query and positional parsing | Wildcard defect; `MaxRows` conflict; escaping/OR/range/sort direction not established | Query condition matrix on typed fields |
| `ExecuteAsyncSingleQuery`, next, release | Usable | First-page rule, casing, finally cleanup | Release failures are swallowed in examples; cancellation/timeouts absent | Multi-page, zero-row, exception, release-failure fixtures |
| `ExecuteAsyncMultiQuery`, next, release | Partial | Initial call, nested response parsing, cleanup, and observed non-pagination | Live pagination trigger condition remains unknown | Large multi-category live fixture or formally mark pagination unsupported |
| `ExecuteFullTextQuery` | Usable | Correct request and flat response in core and Python references | Async variant and advanced syntax remain unverified | Test boolean/phrase/fuzzy/context/index-data options |
| `GetDocumentIndexData` | Partial | Typed scalar items and a table sketch | Helpers flatten complex keyword/table values to empty strings | Typed extractor preserving scalars, keywords, and table rows |
| `GetDocument` | Partial | Flags in bundled client | Endpoint reference says metadata only and omits a full response | Capture metadata/stream-info/index-data combinations |
| `PreprocessIndexData` | Usable | Required wrapper and flags | Response/error examples limited | Fixtures for defaults, calculated and dependent fields |
| `EvaluateConditionalProperties` | Partial | Basic request | Conditional response schema and enforcement workflow missing | Fixture for visible/hidden/mandatory transitions |
| `CreateDocument` | Usable | Four-step workflow, canonical top-level payload, and stream encoding | Live mutation fixture not stored locally | Disposable category tests for index-only and file documents |
| `UpdateDocument2` | Partial | Last-change concurrency pattern | Partial-vs-full item semantics and conditional preprocessing unclear | Concurrent update conflict and each field type |
| `SaveDocumentIndexData` / `UpdateDocument` | Partial | Named and briefly described | No full payload/response examples or comparison table | Test index-only, rename/delete/replace stream scenarios |
| `AddStreamsToDocument` / conversions | Gap | Endpoint names and client wrappers | Stream payloads, conversion options, outputs unverified | DOCX/PDF/text fixtures and failure limits |
| `GetDocumentStream` | Usable | POST contract, raw byte-array handling, and helper test | Live binary fixture/hash not stored locally | Test binary round-trip hashes |
| `DeleteDocument` | Gap | Name and `DocNo` only | Restore/retention/security/error behaviour absent | Disposable create-delete check; document reversibility |
| History / properties / versions | Partial | `GetDocumentHistory`; wrapper aliases versions to history | History response absent; terminology may mislead | Versioned document fixture and method rename |
| Checkout / checkin / undo | Partial | Status, checkout, undo verified | Successful `CheckInDocument` payload explicitly unknown | Upload modified stream and verify new version/status |
| Comments | Usable | Correct load/add/edit object contracts and wrapper payload tests | Live mutation fixture not stored locally | Add disposable load/add/edit live fixture |
| Keyword read/validate | Partial | Field and dictionary lookup examples | Dependent dictionaries and pagination not covered | Cascading keyword field fixture |
| Keyword add/update/delete | Gap | Bundled wrapper only | No docs, permission/error model, or live verification | Disposable dictionary test or label experimental |
| User/group listing | Usable | Verified flags/group contracts and corrected wrapper defaults | Broader identity fixtures remain absent | Add regular, disabled, AD, and empty-group fixtures |
| User CRUD/password/licence/settings | Gap | Bundled wrapper names only | High-risk state changes lack schemas and safety guidance | Separate admin guide; disposable users; explicit warnings |
| Workflow query/history/process/settings | Gap | Some client wrappers and basic task example | Most operations lack endpoint schemas/responses | Read-only inventory fixtures per process/task type |
| `CompleteTask` / claim/disclaim/delegate | Partial | Generated `CompleteTaskParams` contract is canonicalized; claim/disclaim/delegate wrappers remain | Workflow-specific decision values and side effects need live testing | Disposable workflow test for every transition operation |
| Case discovery/read/create/delete | Partial | Correct definition/create/read/history and lifecycle request schemas | Save/link/restore side effects are not live-verified | Test save/link/close/reopen/delete/restore lifecycle |
| Case link/unlink | Partial | Known silent-success caveat | Required link payload and verification unknown | WSDL schema plus link/readback/unlink fixture |
| MCP `therefore_connect` / grouped tools | Partial | High-level routing and known gaps | No locally pinned tool schemas; relies on mutable external repo | Generate a tool-surface manifest from `therefore-mcp` release |
| JavaScript/Formio | Partial | Quick start and external links | No local fixture/build/version compatibility; external repo unchanged since March | Pin library release and add a minimal tested Formio action |
| PowerShell | Partial | Auth and async query patterns | `MaxRows` conflict; no creation/update/stream examples | Pester payload tests and read-only smoke script |

## Recommended implementation sequence

### Phase 1 — stop incorrect code generation

1. Fix F-01 through F-06.
2. Add a repository-wide consistency test for forbidden stale patterns:
   `LIKE ...%`, `SearchText`, singular full-text `CategoryNo`, and base64-decoding raw
   `FileData`.
3. Add JSON request/response fixtures for query, full-text, stream, comments, users, and
   cases; unit-test examples against those fixtures without needing credentials.
4. Put a warning above `references/therefore_client.py` until it is synchronized and its
   conflicting wrappers are fixed.

### Phase 2 — establish canonical contracts

1. Build an operation registry containing endpoint, HTTP verb, request members, response
   shape, mutability, verification date, server version, and source fixture.
2. Resolve F-07 through F-13 with read-only calls first, then disposable state for mutations.
3. Generate the endpoint table and payload snapshot tests from that registry.
4. Decide whether the bundled client is owned here. If yes, test and release it here; if no,
   remove the stale copy and pin the upstream `therefore-mcp` client version.

### Phase 3 — close functional gaps

1. Document and test document updates/streams/conversions/check-in.
2. Document workflow task lifecycle and reconcile completion contracts.
3. Complete case save/link/close/reopen/restore coverage.
4. Separate administrative user/dictionary mutations from ordinary integration guidance and
   add explicit permission/destructive-action notes.
5. Add PowerShell and Formio parity examples only after the raw REST contracts are canonical.

### Phase 4 — maintainability and release hygiene

1. Replace placeholders with a safe smoke-test script.
2. Add CI for Python compile/tests, Markdown links, stale-pattern checks, and local/upstream
   snapshot drift.
3. Add README, licence, contributing guide, changelog, semantic version/tag, and a support
   matrix for Therefore Online/on-prem and tested server versions.
4. Convert dated prose TODOs into GitHub issues and link each issue from the relevant section.

## Remaining live verification

- Confirm `MaxRows` omitted/`0`/`500`/`2147483647` against a category containing more than
  500 accessible documents and record the server version.
- Capture a real multi-query result large enough to exercise `GetNextMultiQueryRows`, if the
  server ever sets `HasRemainingRows`.
- Store redacted binary stream and typed index-data fixtures, including table and multiple
  keyword fields.
- Exercise successful check-in with replacement content.
- Exercise `CompleteTask` using a disposable workflow and record valid `TaskDecision` values.
- Exercise case save/link/unlink/close/reopen/delete/restore with disposable cases and verify
  every mutation through a subsequent read.
- Choose a licence and create the first version tag/release.

## Suggested first GitHub issues

1. **Fix stale wildcard, full-text, and stream Python examples** (F-01–F-03).
2. **Correct `ThereforeClient` case, comments, and users payloads** (F-04–F-06).
3. **Resolve HTTP verb exceptions and remove unsafe `call_endpoint` auto-routing** (F-07).
4. **Verify and canonicalize CreateDocument and CompleteTask contracts** (F-08–F-09).
5. **Fix or deprecate `execute_async_multi_query_all`** (F-10).
6. **Determine `MaxRows: 0` behaviour by server version** (F-11).
7. **Choose ownership/synchronization policy for `therefore_client.py`** (F-12, F-17, F-19).
8. **Add fixture-based contract tests and CI** (F-15, F-18).
9. **Replace scaffold placeholders with a read-only smoke test** (F-14).
10. **Add repository metadata and versioned releases** (F-16).

## Audit boundary

This report covers the files committed to `Fybre/therefore-api-skill` at the audited commit,
the repository metadata and issue list exposed by GitHub, and a drift comparison with the
current raw `therefore-mcp` client linked by the skill. It does not certify the live Therefore
service, the entire 268-operation WSDL, the `therefore-mcp` server implementation, or the
Formio library. Those are explicit next-stage verification targets.
