---
name: therefore-api
description: |
  Therefore REST API integration. Use whenever writing code that interacts with Therefore
  document management — querying, creating, updating documents, reading index data, or
  working with categories via the restun API.

  MANDATORY TRIGGERS: "Therefore", "Therefore Online", "Therefore API", "restun",
  "theservice", "thereforeonline.com", Therefore categories, index fields, document queries,
  Formio eforms, window.Therefore, ThereforeClient (JavaScript).

  Contains correct endpoint URLs, auth patterns (Basic Auth + TenantName header),
  query condition syntax, request/response schemas, Python examples validated against
  live servers, and JavaScript/Formio integration patterns. The API has non-obvious
  conventions that cause 500 errors if guessed wrong — always read this skill BEFORE
  writing Therefore integration code in any language.
---

# Therefore REST API

## Architecture

Therefore exposes a WCF-based REST API under `/restun/`. The named service operations are
**POST** requests with JSON bodies. A small set of route-style utility endpoints use **GET**,
including `GetSystemCustomerId`, `GetDocumentStreamChunks/{docNo}/{versionNo}/{streamNo}`,
`GetUploadedEFormFile/{tenant}/{fileId}`, and `Confirm2FACode/...`. Do not infer the verb from
an operation name; use POST unless the route is explicitly documented as a GET exception.

**URL pattern (Therefore Online / cloud):**
```
https://{tenant}.thereforeonline.com/theservice/v0001/restun/{OperationName}
```

**URL pattern (on-premise):**
```
https://{server}/theservice/v0001/restun/{OperationName}
```

## Authentication

Two authentication methods are supported:

### 1. HTTP Basic Auth (most common)
HTTP Basic Auth on every request. No session tokens or OAuth.

### 2. Bearer Token Auth
Use `GetConnectionToken` to get a token, then pass as `Authorization: Bearer {token}`.

**Therefore Online (cloud) additionally requires a `TenantName` header** — without it,
every request returns a 500 error saying "Tenant name is required." The tenant is the
subdomain: for `https://acme.thereforeonline.com`, the tenant is `acme`.

```python
import requests
from urllib.parse import urlparse

session = requests.Session()
session.auth = (username, password)
session.headers.update({'Content-Type': 'application/json; charset=utf-8'})

# Therefore Online: add tenant header
parsed = urlparse(base_url)
if (parsed.hostname or '').lower().endswith('.thereforeonline.com'):
    tenant = parsed.hostname.split('.')[0]
    session.headers.update({'TenantName': tenant})
```

**Content-Type** must be `application/json; charset=utf-8` (include the charset).

**Test connection:** `POST /restun/GetConnectionToken` with empty body `{}`.
Returns `{"Token": "..."}` on success.

## Query Condition Syntax — Read This First

This is where most mistakes happen. The `Condition` field in queries supports
multiple formats:

**Exact match — just the raw value, NO operator:**
```python
# CORRECT — bare value for exact match:
{"FieldNoOrName": "Invoice_No", "Condition": "67307PAOP"}

# ALSO CORRECT — full expression with field name and quoted value:
{"FieldNoOrName": "Order_No", "Condition": "Order_No = '12345'"}

# WRONG — causes "Syntax error near = 67307PAOP":
{"FieldNoOrName": "Invoice_No", "Condition": "= 67307PAOP"}
```

**Comparison operators — prefix the value:**
```python
{"Condition": ">= 1000"}               # Greater than or equal
{"Condition": "LIKE Acme*"}             # Wildcard — use * not %
{"Condition": "LIKE *"}                 # Match all (wildcard only)
{"Condition": ">= 2024-01-01"}         # Date comparison
```

**Wildcard is `*`, NOT `%`:**
Using `%` returns 0 results silently — no error, just empty. Always use `*`.
```python
# CORRECT:
{"FieldNoOrName": "Supplier_Name", "Condition": "LIKE Acme*"}

# WRONG — silently returns 0 results:
{"FieldNoOrName": "Supplier_Name", "Condition": "LIKE Acme%"}
```

**IS NULL / IS NOT NULL:**
```python
{"FieldNoOrName": "Notes", "Condition": "IS NULL"}
{"FieldNoOrName": "Notes", "Condition": "IS NOT NULL"}
```

**TimeZone in date conditions:**
```python
{
    "FieldNoOrName": "Invoice_Date",
    "Condition": ">= 2024-01-01",
    "TimeZone": "UTC"
}
```

## ExecuteSingleQuery

The synchronous search endpoint. Good for simple queries.

**POST** `/restun/ExecuteSingleQuery`

```json
{
  "Query": {
    "CategoryNo": 8,
    "Conditions": [
      {"FieldNoOrName": "Invoice_No", "Condition": "67307PAOP"}
    ],
    "SelectedFieldsNoOrNames": ["Invoice_No", "Supplier_Name"],
    "MaxRows": 0,
    "RowBlockSize": 200,
    "Mode": 0
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `CategoryNo` | int | Required. Category to search. |
| `Conditions` | array | Each has `FieldNoOrName` (string) and `Condition` (string). |
| `SelectedFieldsNoOrNames` | array | Optional. Fields to return. Omit = all fields. |
| `MaxRows` | int | 0 defaults to 500. Use `2147483647` (int max) for all documents. |
| `RowBlockSize` | int | Page size. |
| `Mode` | int | 0 = normal. |
| `OrderByFieldsNoOrNames` | array | Optional. Fields to sort by. |

**Response:**
```json
{
  "QueryResult": {
    "CategoryNo": 8,
    "QueryID": 12345,
    "Columns": [
      {"FieldNo": 101, "Caption": "Invoice_No", "ColName": "Invoice_No", "FieldType": 0}
    ],
    "ResultRows": [
      {"DocNo": 265461, "VersionNo": 1, "IndexValues": ["67307PAOP"], "Size": 97400}
    ]
  },
  "HasRemainingRows": false
}
```

## ExecuteAsyncSingleQuery

The **preferred** search endpoint for production use. Works identically to
`ExecuteSingleQuery` but processes asynchronously on the server.

**POST** `/restun/ExecuteAsyncSingleQuery`

Request body is identical to `ExecuteSingleQuery`. Key response difference:

```json
{
  "QueryId": 67890,
  "QueryResult": {
    "Columns": [...],
    "ResultRows": [...]
  },
  "HasRemainingRows": true
}
```

**IMPORTANT:** The response includes BOTH the `QueryId` AND the **first page of results**
inside `QueryResult`. Process this first page immediately — do not skip to
`GetNextSingleQueryRows` first, or you will miss all data when results fit on one page
(which is the common case). See pitfall #18.

Note: Returns `QueryId` (lowercase 'd'), not `QueryID` (uppercase 'D') as in
the synchronous variant. Use `GetNextSingleQueryRows` with this ID to fetch
additional pages, and `ReleaseSingleQuery` to release.

**Workflow:**
```python
# 1. Start async query — response contains QueryId AND first page of results
result = client.post("ExecuteAsyncSingleQuery", {"Query": {...}})
query_id = result.get("QueryId")  # Note: lowercase 'd'

try:
    # 2. Process FIRST PAGE from the initial response (critical — do not skip this)
    rows = result.get("QueryResult", {}).get("ResultRows", [])
    # process rows...

    # 3. Fetch further pages only while more remain
    while result.get("HasRemainingRows"):
        result = client.post("GetNextSingleQueryRows", {
            "QueryID": query_id, "RowBlockSize": 200
        })
        rows = result.get("QueryResult", {}).get("ResultRows", [])
        # process rows...
finally:
    # 4. ALWAYS release
    client.post("ReleaseSingleQuery", {"QueryID": query_id})
```

### Parsing Results — Positional Mapping

`Columns` and `IndexValues` are parallel arrays. Column 0 → IndexValues 0, etc.
Never assume field ordering — always build the column map:

```python
columns = query_result.get("Columns", [])
rows = query_result.get("ResultRows", [])

col_map = {i: col.get("ColName") or col.get("Caption")
           for i, col in enumerate(columns)}

for row in rows:
    doc_no = row["DocNo"]
    values = row.get("IndexValues", [])
    fields = {col_map[i]: val for i, val in enumerate(values) if i in col_map}
```

### Pagination

If `HasRemainingRows` is true:
```python
next_result = post(session, "GetNextSingleQueryRows", {
    "QueryID": query_id, "RowBlockSize": 200
})
```

Always release when done:
```python
post(session, "ReleaseSingleQuery", {"QueryID": query_id})
```

## GetDocumentIndexData

Full typed field data for a single document. More detailed than query results.

**POST** `/restun/GetDocumentIndexData`

```json
{"DocNo": 265461}
```

Note: The parameter is `DocNo` (int), not `DocId` or `DocumentId`.

**Response — `IndexDataItems` are typed objects:**

Each item has exactly ONE populated key from:

| Key | Data Type |
|-----|-----------|
| `StringIndexData` | String fields (most common) |
| `IntIndexData` | Integer fields |
| `MoneyIndexData` | Currency fields |
| `DateIndexData` | Date fields |
| `DateTimeIndexData` | DateTime fields |
| `LogicalIndexData` | Boolean fields |
| `SingleKeywordData` | Dropdown (has `KeywordNo` + `DataValue`) |
| `MultipleKeywordData` | Multi-select keywords |
| `TableIndexData` | Table rows (nested — see below) |

**Extract a field:**
```python
def get_field_value(index_data, field_name):
    items = index_data.get("IndexData", {}).get("IndexDataItems", [])
    for item in items:
        for type_key, data in item.items():
            if isinstance(data, dict) and data.get("FieldName") == field_name:
                if type_key == "MultipleKeywordData":
                    return data.get("DataValue", data.get("Keywords", data.get("KeywordNos", [])))
                if type_key == "TableIndexData":
                    return data.get("DataValue", data.get("Rows", []))
                if type_key == "SingleKeywordData" and "DataValue" not in data:
                    return data.get("KeywordNo")
                return data.get("DataValue")
    return None
```

### TableData Structure

Table fields in `GetDocumentIndexData` return structured data:
```json
{
  "TableIndexData": {
    "FieldNo": 200,
    "FieldName": "LineItems",
    "DataValue": [
      {
        "RowNo": 1,
        "DataRowItems": [
          {"StringIndexData": {"FieldNo": 201, "FieldName": "Item", "DataValue": "Item A"}},
          {"IntIndexData": {"FieldNo": 202, "FieldName": "Quantity", "DataValue": 5}},
          {"MoneyIndexData": {"FieldNo": 203, "FieldName": "Price", "DataValue": 29.99}}
        ]
      }
    ]
  }
}
```

**Important:** In query results (`IndexValues`), table data is returned as
concatenated/delimited strings. Use `GetDocumentIndexData` when you need
structured table data.

## Document Creation Workflow

Creating documents is a multi-step process:

### Step 1: GetCategoryInfo
Get the category metadata and field definitions.

### Step 2: PreprocessIndexData
Validate and preprocess index data before saving. Handles default values,
calculated fields, etc.

**POST** `/restun/PreprocessIndexData`
```json
{
  "CategoryNo": 8,
  "IndexData": {
    "IndexDataItems": [...]
  }
}
```

**Note:** Items must be wrapped in `IndexData` — `{"CategoryNo": N, "IndexData": {"IndexDataItems": [...]}}`.
Using `{"CategoryNo": N, "IndexDataItems": [...]}` (without the wrapper) will cause a 500 error.
See pitfall #13.

### Step 3: EvaluateConditionalProperties
Check conditional field rules (visibility, mandatory status, etc.).

**POST** `/restun/EvaluateConditionalProperties`
```json
{
  "CategoryNo": 8,
  "IndexDataItems": [...]
}
```

### Step 4: CreateDocument
Create the document with validated index data and optional file streams.

**POST** `/restun/CreateDocument`
```json
{
  "CategoryNo": 8,
  "IndexDataItems": [...],
  "Streams": [
    {
      "StreamNo": 0,
      "FileName": "invoice.pdf",
      "FileDataBase64JSON": "<base64-encoded-content>",
      "NewStreamInsertMode": 0
    }
  ],
  "DoFillDependentFields": true,
  "WithAutoAppendMode": 0,
  "CheckInComments": "Created via API"
}
```

`CreateDocument` fields are top-level request members; there is no `TheDocument` wrapper.
For JSON uploads, put base64 text in `FileDataBase64JSON`. `FileData` is the byte-array form.
`WithAutoAppendMode: 0` uses the category default; it is not synonymous with "always insert."
Known values are `2` append, `3` replace, `4` no check, `5` error, and `6` skip document.
Use mode `4` only when the integration intentionally requires a new document regardless of
the category's auto-append configuration.

## GetCategoryInfo

Category metadata and field definitions. Useful for validating field names.

**POST** `/restun/GetCategoryInfo`

```json
{"CategoryNo": 8, "IsAccessMaskNeeded": false, "IsSearchFieldOrderNeeded": false}
```

Returns `Name`, `CategoryFields[]` (each with `Caption`, `FieldNo`, type info).

## eForms

There's no operation named anything like "list eForms" in the REST API or WSDL. `Type: 47`
is documented as `eForm` in the `GetObjects` Type-parameter value table (see
[the official `GetObjects` reference](https://therefore.net/help/2023/en-us/AR/SDK/WebAPI/the_webapi_operation_getobjects.html)),
but that documentation doesn't say this call also works as a full tenant-wide eForm
*listing* — that part is only confirmed by live-tenant testing (`Fybre/eform-versioner`
verified it returns an identical set of forms to an exhaustive `FormNo` scan).

**List every eForm in the tenant:**

**POST** `/restun/GetObjects`
```json
{"Flags": 1, "Type": 47}
```

Returns `{"ItemList": [...]}` where each item has `ID` (= `FormNo`), `Name`, `FolderNo`,
`Guid`, and a `Flags` bit that's set exactly when `AnonymousAccessEnabled` is true. It does
**not** include the form's current version number — fetch that per-form via `GetEForm`.

**Fetch one eForm's definition:**

**POST** `/restun/GetEForm`
```json
{"FormNo": 12, "VersionNo": 0}
```

`VersionNo: 0` means "latest". The response's `EForm.FormDefinition` is a Base64-encoded
JSON/Form.io definition — decode it to inspect fields, scripts, or embedded credentials.

**Save a new version of an eForm:**

**POST** `/restun/SaveEForm`

Takes the same shape as `GetEForm`'s response, with a new/modified `FormDefinition` and
`VersionNo` set to create a new version rather than overwrite the current one (Therefore's
own eForm designer has no versioning UI, but the underlying REST operations support it).

**Fallback discovery** if `GetObjects(Type:47)` ever errors or returns empty on some server
version/configuration: since `FormNo` is a plain sequential integer, probe `GetEForm(FormNo, 0)`
across a range and collect the hits, stopping after a long enough run of consecutive misses
past the highest hit found. Slower (round trips scale with the FormNo range scanned, not the
form count) — only use it as a fallback, not the primary path.

## Server Settings (GetSettings family)

Server/tenant configuration (the Solution Designer **Settings** dialog, incl. **Server Logging**)
is readable over REST by **integer setting key**. The official docs list the operations but
publish **no key enumeration** — keys below were found by scanning keys 1–1500 on craigdemo
(Web API 35.0.3.0, Basic auth, read-only; 213 readable keys found).

**POST** `/restun/GetSettings` — batch read, typed values:
```json
{"SettingKeys": [701, 702, 703, 704]}
```
```json
{"Settings": [{"Key": 701, "IntValue": 1}, {"Key": 703, "IntValue": 1020}, ...]}
```
Each item carries **either** `IntValue` **or** `StringValue` (the other member is absent).

**POST** `/restun/GetGlobalSettings` — batch read, values always as strings:
```json
{"Settings": [703, 700]}
```
```json
{"SettingValues": [{"SettingNo": 703, "Value": "1020"}, {"SettingNo": 700, "Value": "<Server>..."}]}
```
`Settings` is a **plain int array** — `[{"SettingNo": 703}]` fails with a deserialization error.

**POST** `/restun/GetSettingString` / `/restun/GetSettingInt` — single key:
```json
{"SettingKey": 703}
```
```json
{"SettingValue": 1020}
```
The type must match: `GetSettingInt` on a string key → 500 `Invalid variant type 8`,
`GetSettingString` on an int key → 500 `Invalid variant type 3`. Use `GetSettings` when unsure.

**Error behaviour (important for discovery):**
- An unknown key fails the **whole batch**: 500 `The ID of the setting N is not in the map of the settings.`
- Some keys are protected: 500 `The Setting N is not accessible.` (key 4 — likely the DB credential).
- So probe unknown ranges **one key per request** (parallelise), then batch the known keys.
- `GetPublicSettings`, `GetPublicSettingString`, `GetPublicSettingInt` returned 500
  `Not enough values returned in GetSettings.` for every key tried (1, 5, 10, 102, 175, 181,
  703, 1021) — public-setting keys appear to be a different, undocumented set.
- Called as an administrator. Whether non-admin users can read these keys is **not yet verified**
  — several keys expose infrastructure (DB server, storage/buffer paths, SMTP, OAuth config).

**Server Logging keys (verified against the Settings > Server Logging tab):**

| Key | Meaning | Type / example |
|-----|---------|----------------|
| 700 | Log mask — XML `<Server><LogMask><V>n</V>…</LogMask></Server>`, 52 positional values | string |
| 701 | Archive mode (1 = Every day; other values = weekly / monthly / by size — unmapped) | int, `1` |
| 702 | Archive weekday (used with weekly mode) | int |
| 703 | Archive time, **minutes after midnight, server time (UTC on Therefore Online)** | int, `1020` = 17:00 UTC |
| 704 | Split size in MB — only used when archiving by file size; it starts a new file, it does not cap total size | int, `10` |

LogMask values: `0` = Do not log, `1` = Log failure, `3` = Log always (`2` presumed Log success —
not yet observed). Positions follow Therefore's internal event order, **not** the order shown in
the dialog; the position → event map has not been established yet (toggle one event at a time
and diff key 700 to map it).

**Other keys observed (meaning inferred from values — treat as provisional):**

| Key | Looks like |
|-----|------------|
| 1, 2, 3, 15 | DB server/database, a DB int, DB login name, DB connection options |
| 100, 101, 600, 604 | SMTP host, sender address, SMTP user, mail settings XML |
| 102 | Tenant web URL |
| 104, 105, 501 | Buffer share path, cache path, full-text share path |
| 131, 222 | Blocked file-extension lists |
| 155, 159 | Allowed preview / media extension lists |
| 174, 175 | Tenant name, default culture (`en-US`) |
| 187, 189 | JWT trusted issuers XML, OAuth settings XML |
| 201, 202 | Office hours XML, holidays XML |
| 912 | Migration schedule/profile XML |
| 1100 | Permission sets XML |
| 1300 | Therefore server name |
| 1301 | Storage status XML `<Exceeded>75</Exceeded><LicensedStorage>100</LicensedStorage>` |

Typical use: config-drift auditing — snapshot keys 700–704 (and other security-relevant keys)
on a schedule and alert on change, e.g. someone lowering logging levels.

## Endpoint Reference

| Endpoint | Purpose | Key Params |
|----------|---------|------------|
| `GetConnectionToken` | Test auth / get bearer token | empty `{}` |
| `GetCategoriesTree` | List categories | empty `{}` |
| `GetCategoryInfo` | Category metadata | `CategoryNo` |
| `ExecuteSingleQuery` | Search (synchronous) | `Query` object |
| `ExecuteAsyncSingleQuery` | Search (async, preferred) | `Query` object |
| `GetNextSingleQueryRows` | Paginate | `QueryID`, `RowBlockSize` |
| `ReleaseSingleQuery` | Free query | `QueryID` |
| `GetDocumentIndexData` | Full doc fields | `DocNo` |
| `GetReferencedTableInfo` | Referenced-table metadata and ID column | `DataTypeNo` |
| `ExecuteDependentFieldsQuery` | List valid reference choices in context | `FieldNo`, current `IndexDataItems`, category/case context |
| `FillDependentFields` | Resolve fields populated by a selected reference | `PrimaryFieldNo`, `IndexDataItems`, exactly one context |
| `GetDocument` | Doc metadata + optional index data | `DocNo`, `IsIndexDataValuesNeeded` |
| `PreprocessIndexData` | Validate/default index data | `CategoryNo`, `IndexData.IndexDataItems` |
| `EvaluateConditionalProperties` | Check field rules | `CategoryNo`, `IndexDataItems` |
| `CreateDocument` | Create document | See `references/api_endpoints.md` |
| `UpdateDocument2` | Update index data | `DocNo`, `IndexData` with `LastChangeTime` |
| `SaveDocumentIndexData` | Save index data | `DocNo`, `IndexData` with `LastChangeTime` |
| `UpdateDocument` | Update index + streams | `DocNo`, `IndexData` with `LastChangeTime` |
| `AddStreamsToDocument` | Add streams to doc | `DocNo`, `StreamsToUpload` |
| `GetConvertedDocStreams` | Get converted streams | `DocNo`, `ConversionOptions` |
| `GetDocumentStream` | Download file content as base64 | `DocNo`, `StreamNo` |
| `DeleteDocument` | Delete document | `DocNo` |

| `ExecuteAsyncMultiQuery` | Query multiple categories | `Queries` array — see pitfall #25 (pagination unreliable) |
| `ExecuteFullTextQuery` | Full text search | `FullTextQuery` object — see pitfalls #29–30 (real field names, indexing gaps) |
| `GetKeywordsByFieldNo` | Keyword lookup by field | `FieldNo` |
| `ExecuteUsersQuery` | List all users | `{"Flags": 4}` — see pitfall #19 |
| `CreateUser` | Create an internal user/group | top-level `Password` + nested `User` |
| `ChangeUserPassword` | Change a specified user's password | `UserName`, `OldPassword`, `NewPassword`, optional `DomainName` |
| `ResetUserPwd` | Trigger forgot-password | `UserInfo` username string |
| `GetConnectedUser` / `GetUserDetails` | Read authenticated/specified user | `Create` / `UserOrGroupId` |
| `GetObjects` | List users + groups combined | `{"Flags": 0, "Type": 11}` |
| `GetUsersFromGroup` | Members of a group | `{"GroupName": "..."}` or `{"GroupId": N}` — see pitfall #21 |
| `UpdateUserGroupAssignment` | Add/remove group memberships | nested `User` + `Assignments[]` |
| `MoveUserLicense` / `SignOut` | Move/release authenticated user's license | empty `{}` |
| `ExecuteTaskInfoQuery` | Query workflow tasks | `QueryMode`, `ViewMode`, `MaxRows` required — see pitfall #32 |
| `GetCategoriesTree` | Full category/folder tree | see pitfall #22 for real response shape |
| `GetDocumentCheckoutStatus` | Check-out state of a doc | `DocNo` |
| `CheckOutDocument` | Lock a doc for editing | `DocNo` |
| `UndoCheckOutDocument` | Release a checkout w/o saving | `DocNo` |
| `CheckInDocument` | Save & release a checkout | `DocNo` + new content — see pitfall #24 |
| `LoadComments` | List comments on a doc | `{"ObjNo": N, "ObjType": 2, "MaxCount": N}` |
| `AddComment` | Add a comment | `{"ObjNo": N, "ObjType": 2, "CommentText": "..."}` |
| `EditComment` | Edit a comment | + `"ID"` (GUID from `LoadComments`) — no `DeleteComment` exists |
| `GetCaseDefinition` | Case definition metadata | `{"CaseDefinitionNo": N}` |
| `CreateCase` | Create a case | `{"CaseDefNo": N}` |
| `GetCase` / `GetCaseDocuments` / `GetCaseHistory` | Read a case | `{"CaseNo": N}` |
| `DeleteCase` | Delete a case | `{"CaseNo": N}` |
| `GetObjects` (eForms) | List every eForm in the tenant | `{"Flags": 1, "Type": 47}` — see **eForms** above and pitfall #38 |
| `GetEForm` | Fetch one eForm's definition | `FormNo`, `VersionNo` (0 = latest) |
| `SaveEForm` | Save a new eForm version | Same shape as `GetEForm`'s response, new `FormDefinition`/`VersionNo` |
| `GetSettings` | Read server settings by int key (typed) | `{"SettingKeys": [700, 703]}` — see **Server Settings** and pitfall #39 |
| `GetGlobalSettings` | Read settings as strings | `{"Settings": [700, 703]}` (plain int array) |
| `GetSettingString` / `GetSettingInt` | Read one setting (type must match) | `{"SettingKey": 703}` → `{"SettingValue": ...}` |

## User & Group Management

The API exposes full user and group membership data — useful for reporting, auditing, and
supplementing XML exports that may not include security data.

The official User operations are `ChangeUserPassword`, `CreateUser`, `ExecuteUsersQuery`,
`GetConnectedUser`, `GetUserDetails`, `GetUsersFromGroup`, `MoveUserLicense`,
`ResetUserPwd`, `SignOut`, and `UpdateUserGroupAssignment`. Important write shapes:

```json
// CreateUser: user properties are nested, not flat
{
  "Password": "initial password",
  "User": {
    "UserName": "jane.smith",
    "DisplayName": "Jane Smith",
    "SMTP": "jane.smith@example.com",
    "UserType": 1,
    "Disabled": false,
    "OneTimePwd": true
  }
}

// ChangeUserPassword
{"UserName": "jane.smith", "OldPassword": "old", "NewPassword": "new"}

// ResetUserPwd: username string, not UserId/SendEmail
{"UserInfo": "jane.smith"}

// UpdateUserGroupAssignment
{
  "User": {"Id": 9},
  "Assignments": [
    {"ThereforeGroup": {"Id": 12}, "Remove": false},
    {"ThereforeGroup": {"Name": "Old Group"}, "Remove": true}
  ]
}
```

`MoveUserLicense {}` moves the authenticated user's license from another node to the
current node; it does not accept source/target user IDs. `SignOut {}` releases the
authenticated user's license on the current node.

### Get All Users

**POST** `/restun/ExecuteUsersQuery`

```json
{"Flags": 4}
```

`Flags=4` returns all regular named users. `Flags=0–3` silently return an empty list.
`Flags=63` returns internal system accounts only.

Each user in the response contains: `UserId`, `UserName`, `DisplayName`, `SMTP`,
`Disabled`, `UserType`, `GUID`.

> **Note:** AD/LDAP integrated accounts return `UserId: 0` — use `UserName` as the stable
> identifier, not the numeric ID.

### Get All Groups

There is no `GetGroups` endpoint (returns 405). Use `GetObjects` instead:

**POST** `/restun/GetObjects`

```json
{"Flags": 0, "Type": 11}
```

Returns `{"ItemList": [...]}` containing both users and groups. Filter by `Data` field:

| Data | Meaning |
|------|---------|
| `1` | User account |
| `2` | System group |
| `3` | Special system principal (e.g. `$TheWFSystem`) |

```python
items = post("GetObjects", {"Flags": 0, "Type": 11}).get("ItemList", [])
groups = [i for i in items if i["Data"] == 2]
```

### Get Group Members

**POST** `/restun/GetUsersFromGroup`

```json
{"GroupName": "THEREFORE_ADMINISTRATORS"}
```

Resolves by name, or by numeric ID via `GroupId` (the group's `ID` from `GetObjects`):
```json
{"GroupId": 1}
```

- `GroupNo` is **not** a valid parameter name — it 500s with "Could not find group
  matching the name provided: '' in domain: ''" (fails loudly, not silently). Use
  `GroupName` or `GroupId`.
- Returns `{"Users": []}` (200 OK) for groups with no members.
- Returns a 500 WSError for unknown group names.

### Full Workflow

```python
import requests

BASE_URL = "https://{tenant}.thereforeonline.com/theservice/v0001/restun"
session = requests.Session()
session.auth = ("username", "password")
session.headers.update({
    "Content-Type": "application/json; charset=utf-8",
    "TenantName": "{tenant}"
})

def post(endpoint, body=None):
    return session.post(f"{BASE_URL}/{endpoint}", json=body or {}).json()

# 1. All users
users = post("ExecuteUsersQuery", {"Flags": 4}).get("Users", [])
user_by_name = {u["UserName"]: u for u in users}

# 2. All groups
items = post("GetObjects", {"Flags": 0, "Type": 11}).get("ItemList", [])
all_groups = [i for i in items if i["Data"] == 2]

# 3. Members per group + reverse map (username -> group names)
group_members = {}
user_groups   = {}
for g in all_groups:
    gname = g["Name"]
    members = post("GetUsersFromGroup", {"GroupName": gname}).get("Users", [])
    group_members[gname] = members
    for u in members:
        user_groups.setdefault(u["UserName"], []).append(gname)
```

### Discovering Endpoints via WSDL

The full WSDL listing ~268 operations is available at the **service** path (not the restun path):

```
GET https://{tenant}.thereforeonline.com/theservice/v0001?wsdl
```

> `GET .../restun?wsdl` returns **405**. Use the path above.

```python
import re, requests
r = requests.get(
    "https://{tenant}.thereforeonline.com/theservice/v0001?wsdl",
    auth=("username", "password")
)
ops = sorted(set(re.findall(r'wsdl:operation name="([^"]+)"', r.text)))
```

## Using Therefore via the MCP Server (therefore-mcp)

Everything above describes calling the REST API directly. If an MCP client (e.g. Claude
Code with the `therefore-mcp` server connected) is available, prefer its grouped tools
over hand-rolled REST calls — they wrap auth, tenant headers, pagination, and the
pitfalls above, and are kept in sync with this skill (see "Keeping Knowledge in Sync"
below).

**Tool surface:** one router tool plus grouped operation tools, each taking an
`operation` enum parameter instead of exposing one MCP tool per API endpoint:

| Tool | Covers |
|------|--------|
| `ask_therefore_expert` | Natural-language router — describe what you want, get back the exact tool/operation/parameters to call. Start here. |
| `therefore_connect` | Register a tenant/login at runtime (see below). |
| `therefore_system` | Customer ID, connected user, version, ADFS/SSO token exchange, objects/statistics, log files. |
| `therefore_categories` | Category tree/info, field listing, referenced-table metadata/query, dependent-field query/fill, high-level referenced-field resolution, config generation. |
| `therefore_documents` | Get/create/update/delete, history, checkout/checkin, streams, comments. |
| `therefore_query` | Single/multi/full-text search, pagination, release. |
| `therefore_workflow` | Tasks, task completion, claim/disclaim/delegate, Cases and case index saves. |
| `therefore_users` | Search, create, get details, group membership. |
| `therefore_keywords` | Get by field/dictionary, add. |
| `therefore_knowledge` | Search the server's local knowledge base. |

Most calls need a `tenant` argument selecting which configured tenant/login to use.
If omitted, the server infers it (single configured tenant, or the last tenant used in
the session).

### therefore_connect — registering a tenant/login without restarting the server

By default the server's tenant list is fixed at process startup from server-side env
vars (`THEREFORE_TENANTS` + per-tenant `THEREFORE_<NAME>_BASE_URL`/`_USERNAME`/`_PASSWORD`).
`therefore_connect` adds a tenant/login at **runtime** instead — no config file edit, no
restart:

```json
{"tenant_name": "acme", "username": "jdoe", "password": "..."}
```

- `tenant_name` is the Therefore Online subdomain shorthand (for `acme.thereforeonline.com`)
  — the base URL and the `TenantName` header (see pitfall #1 above) are derived from it
  automatically. For on-prem or non-standard hosts, pass `base_url` explicitly instead
  (and still pass `tenant_name` if the host is a Therefore Online tenant, per the same
  pitfall).
- The call **verifies the login** (`GetConnectionToken`) before registering anything —
  bad credentials fail immediately and nothing gets added to the tenant list.
- On success it returns a `tenant_key` (defaults to a normalized `tenant_name`/`base_url`,
  or set one explicitly via `tenant_key`). Pass that as `"tenant"` on every subsequent
  tool call — or omit `tenant` entirely, since the newly connected tenant becomes the
  session default.
- **In-memory only** — not persisted to disk. A server restart forgets it; that's by
  design, for ad hoc/flexible use rather than permanent config.
- **Scoped per caller** when the server runs in multi-client HTTP mode: a tenant you
  register is only usable by the API key that registered it, not shared with other
  connected clients.
- `ask_therefore_expert` understands connect-flavored questions ("how do I connect to a
  new tenant", "add a different login") and routes straight to `therefore_connect` with
  the parameters spelled out — this works even on a freshly started server with zero
  tenants configured.

### Known gaps in the MCP tool surface (as of 2026-08-05)

- `therefore_documents` has **no document-copy operation** — the underlying
  `CopyDocument` endpoint doesn't exist on the live server (confirmed via WSDL) and no
  replacement was found, so the operation was removed entirely rather than left in as a
  guaranteed-to-fail stub.
- Generic referenced-field support is exposed through `therefore_categories`, including
  `get_referenced_table_info`, `execute_dependent_fields_query`, `fill_dependent_fields`,
  and `resolve_referenced_field`; it works with category, existing-document, and case
  contexts. The workflow tool retains the two low-level dependent-field operations as
  compatibility aliases. Cases also support definition/create/read/documents/history and
  quick/full index saves. `LinkCaseToDocument`, `CloseCase`/`ReopenCase`/`DeleteCase`, and
  `LinkCases`/`UnlinkCases` are not wired up yet.
- `therefore_query`'s `search`/`search_async` operations do **not** support filtering by
  case — see pitfall #28. To answer "what categories/documents belong to this case", use
  `therefore_workflow`'s `get_case_definition` (categories) and `get_case_documents`
  (document numbers), not a `Query` with `CaseDefinitionNo`.

## Extended References

Fetch these on demand for deeper detail:

| Resource | URL |
|----------|-----|
| Official Therefore WebAPI operation reference | https://therefore.net/help/2023/en-us/AR/SDK/WebAPI/the_webapi_reference.html |
| Full endpoint schemas (all operations, request/response) | `references/api_endpoints.md` |
| Python examples (raw REST + ThereforeClient wrapper) | https://raw.githubusercontent.com/Fybre/therefore-mcp/f32d54f489c73f12025ad19bb03a5be017f49a6a/docs/PYTHON_EXAMPLES.md |
| Python quick reference (field types, patterns, ~850 tokens) | https://raw.githubusercontent.com/Fybre/therefore-mcp/f32d54f489c73f12025ad19bb03a5be017f49a6a/docs/PYTHON_QUICK_REFERENCE.md |
| ThereforeClient source (Python MCP client) | https://raw.githubusercontent.com/Fybre/therefore-mcp/f32d54f489c73f12025ad19bb03a5be017f49a6a/src/therefore_client.py |
| MCP server source (tool definitions, dispatch, ask_therefore_expert router, therefore_connect) | https://raw.githubusercontent.com/Fybre/therefore-mcp/f32d54f489c73f12025ad19bb03a5be017f49a6a/src/mcp_server.py |
| PowerShell patterns (reserved vars, async pagination, SecureString) | `references/powershell_reference.md` |
| Redacted live validation results | `references/live_validation.md` |
| JavaScript/Formio reference (browser library, window.Therefore) | https://raw.githubusercontent.com/Fybre/Therefore-Formio-Javascript/7d6dbba46e462231be73f3a83a6acf930d24b73c/docs/javascript_formio_reference.md |
| JavaScript/Formio examples (complete Formio custom action patterns) | https://raw.githubusercontent.com/Fybre/Therefore-Formio-Javascript/7d6dbba46e462231be73f3a83a6acf930d24b73c/examples.js |

## JavaScript / Formio Integration

For browser-based Formio eform development, the Therefore Formio JavaScript library
(`window.Therefore`) is the correct integration layer — not direct fetch calls.

**Key difference from Python/PowerShell:**
- Auth comes from `getConfigurationFromLocalStorage()` — reads the portal's localStorage
- `ThereforeClient` handles Bearer token auth automatically from the portal session
- No credentials need to be embedded in eform scripts

**Quick start:**
```javascript
const { ThereforeClient, IndexData, QueryDefinition, Condition,
        getConfigurationFromLocalStorage } = window.Therefore;

// Build client from portal session (no credentials needed)
const config = getConfigurationFromLocalStorage();
const client = new ThereforeClient({ baseUrl: config.apiUrl, token: config.token, tenant: config.tenant });

// Query a referenced table
const result = await client.queryReferencedTable(
    'My_Referenced_Table',
    [{ FieldNoOrName: 'Field', Condition: '*' }]
);

// Build and save index data
const indexData = new IndexData()
    .addString('Invoice_No', data.invoiceNo)
    .addDate('Invoice_Date', new Date())
    .addKeyword('Status', 'Approved');

await client.execute('SaveDocumentIndexDataQuick',
    new (window.Therefore.SaveDocumentIndexDataQuickParams)(docNo, indexData));
```

For the full API surface, patterns, and Formio-specific integration examples,
fetch the JavaScript/Formio reference URL above.

## Common Pitfalls

1. **Missing TenantName header** → 500: "Tenant name is required." Always add
   `TenantName` header for Therefore Online.

2. **Using `= value` in Condition** → 500: "Syntax error near = value." Use the
   raw value for exact match — no `=` prefix.

3. **Named service operations are POST** → Route-style utilities are the exception. Confirmed
   GET routes include `GetSystemCustomerId`, `GetDocumentStreamChunks/...`,
   `GetUploadedEFormFile/...`, and `Confirm2FACode/...`. In particular, `GetDomainInfo` and
   `GetDocumentStream` are POST operations; do not route every endpoint beginning with `Get`
   through HTTP GET.

4. **Parameter is `DocNo` not `DocId`** → Consistent across all endpoints.

5. **Keyword fields need KeywordNos for writes** → Creating/updating keyword fields
   requires the numeric `KeywordNo`, not the display string. Resolve with
   `GetKeywordsByFieldNo` (pass `FieldNo` + `CategoryNo`).

6. **Table data in query results is concatenated** → `IndexValues` for table fields
   are delimited strings. Use `GetDocumentIndexData` for structured table data.

7. **Query results are positional** → `IndexValues[0]` maps to `Columns[0]`. Always
   build the column map from the `Columns` array.

8. **Content-Type needs charset** → Use `application/json; charset=utf-8`, not just
   `application/json`.

9. **AsyncQuery returns `QueryId` (lowercase d)** → `ExecuteAsyncSingleQuery` returns
   `QueryId`, but `GetNextSingleQueryRows` and `ReleaseSingleQuery` expect `QueryID`
   (uppercase D). Map accordingly.

10. **Always release queries in a finally block** → Server resources leak if queries
    aren't released. Use try/finally pattern.

11. **Document creation requires preprocessing** → Call `PreprocessIndexData` and
    `EvaluateConditionalProperties` before `CreateDocument` to handle defaults,
    calculated fields, and conditional rules.

12. **Updating index data does NOT use `UpdateDocumentIndexData`** → The actual
    update endpoints are `UpdateDocument2`, `SaveDocumentIndexData`, or `UpdateDocument`.
    All three require `LastChangeTime` or `LastChangeTimeISO8601` from the current document
    (fetch via `GetDocumentIndexData` first). Without it, the request fails.

13. **`PreprocessIndexData` wraps items in `IndexData`** → The request body is:
    `{"CategoryNo": N, "IndexData": {"IndexDataItems": [...]}}` — NOT just
    `{"CategoryNo": N, "IndexDataItems": [...]}`.

14. **`GetDocumentStream` returns `FileData` as a raw byte array, not base64** → In JSON
    responses, `FileData` is a byte array. Use `bytes(result["FileData"])` in Python or
    `[byte[]]$response.FileData` in PowerShell. Do NOT call `base64.b64decode()` on it.

15. **`GetDictionaryInfo` → use `GetKeywordsByFieldNo` instead** → The correct endpoint
    for resolving keyword values by field is `GetKeywordsByFieldNo` (pass `FieldNo`).

16. **The standalone reference client uses `urllib`, not `requests`** →
    `references/therefore_client.py` uses stdlib `urllib.request` only. Its
    `ThereforeConfig` dataclass controls auth via `auth_method` (`'basic'` or `'bearer'`),
    tenant headers, and timeout settings. It is a focused, tested reference client, not a
    vendored copy of the complete `therefore-mcp` implementation; use the pinned upstream
    source in Extended References for the MCP client's full surface.

17. **Wildcard is `*` not `%`** → Using `%` in `LIKE` conditions returns 0 results
    silently — no error. The correct wildcard character is `*`. E.g. `"LIKE Acme*"`,
    not `"LIKE Acme%"`. This applies to all query endpoints.

18. **`ExecuteAsyncSingleQuery` returns the first page in its own response** → The
    `QueryResult` inside the initial response already contains the first page of rows.
    Do NOT call `GetNextSingleQueryRows` before processing this first page — if all results
    fit on one page, `GetNextSingleQueryRows` returns nothing. Pattern:
    process `result["QueryResult"]`, then loop `while result["HasRemainingRows"]`.

19. **`ExecuteUsersQuery` requires `Flags=4` to return users** → `Flags=0`, `1`, `2`,
    and `3` all silently return an empty list. Use `Flags=4` for all regular named users.
    `Flags=63` returns only internal system accounts.

20. **No `GetGroups` endpoint** → A `GetGroups` call returns 405. Use
    `GetObjects {"Flags":0,"Type":11}` instead and filter the `ItemList` by `Data==2`
    to isolate groups (`Data==1` = users, `Data==3` = system principals).

21. **`GetUsersFromGroup` accepts `GroupName` or `GroupId`, not `GroupNo`** → Use the
    string `GroupName`, or the numeric `GroupId` (the group's `ID` field from `GetObjects`).
    `GroupNo` is not a recognized parameter — it 500s ("Could not find group matching the
    name provided") rather than silently being ignored. An unknown group name/ID also
    returns a 500 WSError.

22. **`GetCategoriesTree` returns `TreeItems`, not `CategoriesTree`** → Items nest under
    `ChildItems` (not `Children`), and the ID field is `ItemNo`, typed by `ItemType`:
    `1` = folder (`ItemNo` is a `FolderNo`), `2` = category (`ItemNo` is a `CategoryNo` —
    only these are queryable/document-bearing), `3` = case definition. Walk the tree
    recursively and filter on `ItemType == 2` to get queryable categories.

23. **`GetDocumentVersions` and `GetComments` don't exist on the live server** → Some
    client library wrappers reference these names, but the real API 405s on
    `GetDocumentVersions`, and the comments endpoint is `LoadComments` (requires
    `ObjNo`, `ObjType`, `MaxCount` — use `ObjType: 2` for a document; `0`/`1` fail with
    "Unsupported object type for comment").

24. **`CheckInDocument` needs actual content to check in** → Calling it with just
    `{"DocNo": ...}` and no changes fails with "The document file is not open." If you
    only need to release a checkout without saving changes, use `UndoCheckOutDocument`
    instead.

25. **`ExecuteAsyncMultiQuery` does not reliably paginate** → Unlike
    `ExecuteAsyncSingleQuery`, testing showed `RowBlockSize` had no effect — all rows for
    each category came back inline in the first response with `HasRemainingRows: false`,
    even when `RowBlockSize` was set well below the actual row count. `GetNextMultiQueryRows`
    exists but its trigger condition wasn't reproduced. For large result sets, use
    `ExecuteAsyncSingleQuery` per category instead — its pagination is confirmed reliable.

26. **`GetCaseDefinition` takes `CaseDefinitionNo`, not `CaseDefNo`** → Despite the response
    field being named `CaseDefNo`, the request parameter is the longer `CaseDefinitionNo`.
    `CreateCase`, by contrast, does use `CaseDefNo`. Case definitions are discoverable via
    `GetCategoriesTree` nodes with `ItemType: 3` (pitfall #22).

27. **`LinkCaseToDocument` returns success but may not actually link** → In testing,
    `{"CaseNo": N, "DocNo": N}` returned `200 {}` but the document did not subsequently
    appear in `GetCaseDocuments`. Verify the link took effect before relying on it — the
    minimal payload may be missing a required field (e.g. `CategoryNo`).

28. **`Query.CaseDefinitionNo` does not filter documents by case** → It looks like a
    case-scoped analog to `CategoryNo`, but it isn't one. Without `CategoryNo` it 500s
    ("Failed to load information from database: Category - ID=..."); with `CategoryNo`
    it's silently dropped (`QueryResult.CaseDefinitionNo` comes back `0`, results are
    identical to a plain `CategoryNo` query). There is no query-time case filter — use
    `GetCaseDocuments` to list a case's document numbers instead, or `CategoryNo` from
    `GetCaseDefinition`'s `Categories` list if you need to actually query.

29. **`ExecuteFullTextQuery`'s real request shape is `Search`/`Categories`, not
    `SearchText`/`CategoryNo`** → The field names in some older docs/examples are wrong.
    The live server requires `Search` (string), `Categories` (array — `[]` means all
    categories, not none), plus `ContextMode`, `SearchScope`, and `SortOrder` — omit any
    of those and it 500s ("required data members ... were not found"). The response is
    also a flat `{"Results": [...]}` array with `MatchedWords`/`Relevance` per hit, not
    the `QueryResult`/`Columns`/`ResultRows` shape `ExecuteSingleQuery` uses.

30. **A category having `IsFulltextEnabled: true` doesn't mean every document in it is
    full-text searchable** → Verified against a live tenant: a document with `IsFulltextEnabled`
    on its category, and confirmed real text content in its PDF (extracted and read
    directly), still returned zero full-text hits — even when the query was scoped to
    only that document's category. There's no REST endpoint to trigger a reindex (checked
    the live WSDL operation list). If a full-text search seems to be missing a document
    you know contains the term, don't assume the query is wrong — the document may
    simply not be in the full-text index yet (failed/pending indexing), which needs
    checking from the Therefore admin console, not the API.

31. **Do not add a max `RoleAccessMask` to `GetObjects` by default** → On craigdemo Web API
    35.0.3.0, `{"Flags":0,"Type":11}` returned 32 objects, while adding
    `RoleAccessMask: 18446744073709551615` returned zero. Permission filters are opt-in.

32. **`ExecuteTaskInfoQuery` requires `QueryMode` and `ViewMode`** → An empty `{}` body fails
    deserialization on Web API 35.0.3.0. Use at least
    `{"QueryMode":0,"ViewMode":0,"MaxRows":1000}`. Results are under `QueryResult`, not
    `TaskInfos`.

33. **`WithAutoAppendMode: 0` uses the category default** → A broken category auto-append
    configuration can make `CreateDocument` fail even when preprocessing succeeds. Mode `4`
    means "No check" and created a new disposable document successfully on craigdemo, but it
    bypasses duplicate/append rules and must be chosen deliberately.

34. **Referenced-table fields store the referenced row ID, not free text** → Determine the
    data type of the referenced table's ID field and use the corresponding typed index-data
    object. The value must identify an existing permitted row in the referenced table. For
    example, a string-backed reference uses `StringIndexData`, but only a valid stored string
    ID can be saved; a reference backed by an integer ID uses `IntIndexData` instead.

    Use `GetReferencedTableInfo` with the field's `TypeNo` to find `IndexColumn` and its
    column type. Use `ExecuteDependentFieldsQuery` to enumerate values valid for the current
    category/case and current index values. After selecting a returned ID, pass it to
    `FillDependentFields`; save the returned `UpdatedIndexDataItems`, not just the primary ID.

35. **`FillDependentFields` context members must be omitted, not zero-filled** → Specify
    exactly one of `DocNo`, `CategoryNo`, or `CaseDefinitionNo`. Sending `DocNo: 0` alongside
    `CategoryNo: 0` fails because `DocNo` and `CategoryNo` are mutually exclusive. For case
    index data, send `CaseDefinitionNo` and omit both document and category members.

36. **`ExecuteDependentFieldsQuery` also requires one real definition context** → Specify
    exactly one of `CategoryNo` or `CaseDefinitionNo`; omit the other member. For a new
    category document, first call `PreprocessIndexData` and pass its complete typed
    `IndexDataItems`. For an existing document, pass the complete current items and category
    number from `GetDocumentIndexData`. The grouped MCP helper
    `therefore_categories.resolve_referenced_field` automates metadata lookup, preprocessing,
    valid-row querying, typed ID selection, and dependent-field filling.

37. **User-operation payloads are structured and identity-scoped** → `CreateUser` requires
    a nested `User` object; `ChangeUserPassword` includes the target `UserName`;
    `ResetUserPwd` accepts `UserInfo` rather than `UserId`/`SendEmail`; and
    `UpdateUserGroupAssignment` uses nested `User` and `Assignments` objects.
    `MoveUserLicense` and `SignOut` both take `{}` and operate on the authenticated user.

38. **There's no "list eForms" operation — use `GetObjects {"Flags": 1, "Type": 47}`** → Type 47
    ("eForm") is a documented `GetObjects` Type value, but the docs don't say this also works as
    a tenant-wide eForm listing — that's only confirmed by live-tenant testing (matches an
    exhaustive `FormNo` scan exactly). The response has no version number; fetch each form's
    latest via `GetEForm(FormNo, VersionNo: 0)`. See **eForms** above.

39. **Setting keys are undocumented integers, and one bad key fails the whole batch** →
    `GetSettings`/`GetGlobalSettings` return 500 (`The ID of the setting N is not in the map of
    the settings.`) if *any* key in the list is unknown, and `The Setting N is not accessible.`
    for protected keys. Discover keys one per request, then batch. `GetGlobalSettings.Settings`
    is a plain int array, not `[{"SettingNo": n}]`. `GetSettingInt`/`GetSettingString` fail with
    `Invalid variant type` if the key's type doesn't match. Server Logging lives at keys 700–704
    (703 = archive time in minutes, UTC). See **Server Settings** above.

## Keeping Knowledge in Sync

This skill references live content from GitHub raw URLs (see Extended References above).
The therefore-mcp server maintains a parallel local knowledge base (`docs/knowledge-base.json`)
queried by the `therefore_knowledge` MCP tool.

**When you discover a new API quirk, update a workflow, or correct a pattern, update both:**
1. The relevant section in this skill's source files (therefore-api-skill repo)
2. The corresponding entry in `therefore-mcp/docs/knowledge-base.json`

Repos:
- https://github.com/Fybre/therefore-api-skill
- https://github.com/Fybre/therefore-mcp
- https://github.com/Fybre/Therefore-Formio-Javascript
