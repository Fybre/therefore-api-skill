# Therefore REST API — Endpoint Reference

All endpoints are POST requests to `{base_url}/restun/{EndpointName}`.
Content-Type: `application/json; charset=utf-8`

## Table of Contents

- [Connection & Auth](#connection--auth)
- [Categories](#categories)
- [Queries](#queries)
- [Documents](#documents)
- [Comments](#comments)
- [Users](#users)
- [Keywords](#keywords)
- [Workflows](#workflows)
- [Cases](#cases)
- [Error Handling](#error-handling)

---

## Connection & Auth

### GetConnectionToken

Test authentication and get a session/bearer token.

```json
// Request: (empty body)
{}

// Response:
{"Token": "abc123def456..."}
```

The token can be used for Bearer auth: `Authorization: Bearer {token}`

### GetDomainInfo

Get server/domain information.

```json
// Request:
{}

// Response:
{"DomainName": "...", "ServerVersion": "...", ...}
```

---

## Categories

### GetCategoriesTree

List the full folder/category/case-definition tree the user has access to.

```json
// Request:
{}

// Response:
{
  "TreeItems": [
    {
      "ItemNo": 172,
      "ItemType": 1,
      "Name": "Archive",
      "FolderType": 3,
      "ParentFolderNo": 1,
      "ParentCaseDefNo": 0,
      "Guid": "5e382580-b3b6-4837-b090-a0a87e5c17f5",
      "ChildItems": [
        {
          "ItemNo": 56,
          "ItemType": 2,
          "Name": "Test Category",
          "FolderType": 0,
          "ParentFolderNo": 105,
          "ParentCaseDefNo": 0,
          "Guid": "...",
          "ChildItems": []
        }
      ]
    }
  ]
}
```

**IMPORTANT — this does not match older docs/examples that show `CategoriesTree`/`CategoryNo`/`Children`.**
The live response key is `TreeItems`, and items nest under `ChildItems` (recursively — walk it
depth-first to flatten). Each item's `ItemNo` is the ID for whatever `ItemType` it is:

| `ItemType` | Meaning | `ItemNo` is a... |
|---|---|---|
| `1` | Folder | `FolderNo` |
| `2` | Category (leaf — use with `GetCategoryInfo`/`ExecuteSingleQuery`) | `CategoryNo` |
| `3` | Case definition | `CaseDefNo` |

Only `ItemType: 2` nodes are queryable documents categories. Verified against a live tenant
2026-07-16: an `ItemNo` from an `ItemType: 2` node passed straight into
`GetCategoryInfo.CategoryNo` returns that category's field definitions correctly.

### GetCategoryInfo

Get detailed category metadata including all field definitions.

```json
// Request:
{
  "CategoryNo": 8,
  "IsAccessMaskNeeded": false,
  "IsSearchFieldOrderNeeded": false
}

// Response:
{
  "Name": "Invoices",
  "CategoryNo": 8,
  "CategoryFields": [
    {
      "FieldNo": 101,
      "Caption": "Invoice_No",
      "FieldType": 0,
      "IsMandatory": false,
      "IsSearchField": true,
      "MaxLength": 255
    },
    {
      "FieldNo": 102,
      "Caption": "Amount",
      "FieldType": 3,
      ...
    }
  ]
}
```

**FieldType values:**
| Value | Type |
|-------|------|
| 0 | String |
| 1 | Integer |
| 2 | Date |
| 3 | Money |
| 4 | Logical (boolean) |
| 5 | Single Keyword |
| 6 | Multiple Keywords |
| 7 | Table |
| 8 | DateTime |

---

## Queries

### ExecuteSingleQuery

Search documents in a category with field conditions (synchronous).

```json
// Request:
{
  "Query": {
    "CategoryNo": 8,
    "Conditions": [
      {
        "FieldNoOrName": "Invoice_No",
        "Condition": "67307PAOP"
      }
    ],
    "SelectedFieldsNoOrNames": ["Invoice_No", "Supplier_Name"],
    "OrderByFieldsNoOrNames": ["Invoice_No"],
    "MaxRows": 0,
    "RowBlockSize": 200,
    "Mode": 0
  }
}

// Response:
{
  "QueryResult": {
    "CategoryNo": 8,
    "QueryID": 12345,
    "Columns": [
      {
        "FieldNo": 101,
        "Caption": "Invoice_No",
        "ColName": "Invoice_No",
        "FieldType": 0,
        "Visible": true
      }
    ],
    "ResultRows": [
      {
        "DocNo": 265461,
        "VersionNo": 1,
        "IndexValues": ["67307PAOP"],
        "Size": 97400,
        "Status": 0,
        "AccessMask": {"Value": 18446744073709551615},
        "RoleAccessMask": {"Value": 18446744073709551615}
      }
    ]
  },
  "HasRemainingRows": false
}
```

**Query field reference:**
| Field | Type | Notes |
|-------|------|-------|
| `CategoryNo` | int | Required. Category to search |
| `Conditions` | array | Field conditions (AND logic) |
| `SelectedFieldsNoOrNames` | array | Fields to return (omit = all) |
| `OrderByFieldsNoOrNames` | array | Sort fields |
| `MaxRows` | int | 0 defaults to 500. Use `2147483647` (int max) for all documents. |
| `RowBlockSize` | int | Page size |
| `Mode` | int | 0 = normal |

**Condition syntax:**
- Exact match: `"67307PAOP"` (just the value)
- Full expression: `"Order_No = '12345'"` (field name + operator + quoted value)
- Greater than: `">= 1000"`
- Wildcard: `"LIKE Acme%"`
- Between: `">= 2024-01-01 AND <= 2024-12-31"`
- Null check: `"IS NULL"` or `"IS NOT NULL"`
- With timezone: add `"TimeZone": "UTC"` to the condition object
- **WRONG**: `"= 67307PAOP"` (operator without field name causes syntax error)

### ExecuteAsyncSingleQuery

**Preferred** search endpoint. Same request as ExecuteSingleQuery, different response.
```json
// Request: (same as ExecuteSingleQuery)
{
  "Query": {
    "CategoryNo": 8,
    "Conditions": [...],
    "SelectedFieldsNoOrNames": [...],
    "MaxRows": 0,
    "RowBlockSize": 200,
    "Mode": 0
  }
}

// Response: contains QueryId AND the first page of results
{
  "QueryId": 67890,
  "QueryResult": {
    "CategoryNo": 8,
    "Columns": [
      {"FieldNo": 101, "Caption": "Reference", "ColName": "Reference", "FieldType": 0}
    ],
    "ResultRows": [
      {"DocNo": 265461, "VersionNo": 1, "IndexValues": ["INV-001"], "Size": 97400}
    ]
  },
  "HasRemainingRows": true
}
```

**CRITICAL:** The initial response contains the **first page of ResultRows and Columns**,
not just the QueryId. Process this data immediately — do NOT discard it and jump straight
to `GetNextSingleQueryRows`. When all results fit in one page (the common case),
`GetNextSingleQueryRows` will return nothing because the data was already delivered here.

**Correct pagination workflow:**
1. Call `ExecuteAsyncSingleQuery` → process `QueryResult` from this response as page 1
2. Check `HasRemainingRows` — only call `GetNextSingleQueryRows` if `true`
3. Repeat until `HasRemainingRows` is `false`
4. Always call `ReleaseSingleQuery` in a finally/ensure block

**IMPORTANT:** Response uses `QueryId` (lowercase 'd'). `GetNextSingleQueryRows` and
`ReleaseSingleQuery` both use `QueryID` (uppercase 'D') in their request bodies.

### GetNextSingleQueryRows

Fetch next page of results from an active query.

```json
// Request:
{
  "QueryID": 12345,
  "RowBlockSize": 200
}

// Response: (same structure as ExecuteSingleQuery response)
```

### ReleaseSingleQuery

Free server resources for a completed query. Always call this when done.

```json
// Request:
{"QueryID": 12345}

// Response: (empty on success)
```

---

### ExecuteAsyncMultiQuery

Query multiple categories simultaneously in a single API call.

```json
// Request:
{
  "Queries": [
    {
      "CategoryNo": 8,
      "Conditions": [{"FieldNoOrName": "Status", "Condition": "Pending"}],
      "SelectedFieldsNoOrNames": ["Invoice_No", "Amount"],
      "MaxRows": 0,
      "RowBlockSize": 200,
      "Mode": 0
    },
    {
      "CategoryNo": 12,
      "Conditions": [],
      "SelectedFieldsNoOrNames": ["PO_Number", "Supplier"],
      "MaxRows": 0,
      "RowBlockSize": 200,
      "Mode": 0
    }
  ]
}

// Response:
{
  "QueryResults": [
    {
      "QueryResult": {
        "CategoryNo": 8,
        "Columns": [...],
        "ResultRows": [...]
      }
    },
    {
      "QueryResult": {
        "CategoryNo": 12,
        "Columns": [...],
        "ResultRows": [...]
      }
    }
  ]
}
```

**Notes:**
- `QueryResults[i]` corresponds to `Queries[i]` by position.
- A `QueryId` IS returned (singular, covering the whole multi-query batch), and
  `GetNextMultiQueryRows`/`ReleaseMultiQuery` exist as the pagination/cleanup endpoints —
  but in live testing 2026-07-16, `HasRemainingRows` came back `false` and all rows for
  each category were returned inline in the initial response **regardless of
  `RowBlockSize`** (a `RowBlockSize: 2` request against a 7-row category still returned
  all 7 rows with `HasRemainingRows: false`). `ExecuteAsyncMultiQuery` does not appear to
  paginate the way `ExecuteAsyncSingleQuery` does — treat `RowBlockSize` here as advisory
  at best. `GetNextMultiQueryRows`'s actual trigger condition (if any) was not reproduced.
- Always call `ReleaseMultiQuery {"QueryID": ...}` when done (confirmed working) — same
  cleanup discipline as `ReleaseSingleQuery`.
- For very large result sets, prefer separate `ExecuteAsyncSingleQuery` calls per category,
  since that's the endpoint with confirmed working pagination.

---

## Documents

### GetDocumentIndexData

Get all index field values for a specific document.

```json
// Request:
{
  "DocNo": 265461
}

// Response:
{
  "DocNo": 265461,
  "IndexData": {
    "CategoryNo": 8,
    "CtgryName": "Invoices",
    "DocNo": 265461,
    "VersionNo": 1,
    "Title": "Invoice 67307PAOP",
    "LastChangeTime": "/Date(1698278400000+0000)/",
    "IndexDataItems": [
      {
        "StringIndexData": {
          "FieldNo": 101,
          "FieldName": "Invoice_No",
          "DataValue": "67307PAOP"
        }
      },
      {
        "MoneyIndexData": {
          "FieldNo": 103,
          "FieldName": "Invoice_Total",
          "DataValue": 1809.56
        }
      },
      {
        "SingleKeywordData": {
          "FieldNo": 105,
          "FieldName": "Status",
          "KeywordNo": 42,
          "DataValue": "Preapproved"
        }
      },
      {
        "DateIndexData": {
          "FieldNo": 106,
          "FieldName": "Invoice_Date",
          "DataValue": "/Date(1697760000000+0000)/"
        }
      },
      {
        "TableIndexData": {
          "FieldNo": 200,
          "FieldName": "LineItems",
          "Rows": [
            {
              "Values": [
                {"StringValue": "Item A"},
                {"IntValue": 5},
                {"MoneyValue": 29.99}
              ]
            }
          ]
        }
      }
    ]
  }
}
```

**IndexDataItem type keys:**
| Key | Data Type | Value Field |
|-----|-----------|-------------|
| `StringIndexData` | String | `DataValue` (string) |
| `IntIndexData` | Integer | `DataValue` (int) |
| `MoneyIndexData` | Currency | `DataValue` (decimal) |
| `DateIndexData` | Date | `DataValue` (WCF date string) |
| `DateTimeIndexData` | DateTime | `DataValue` (WCF date string) |
| `LogicalIndexData` | Boolean | `DataValue` (bool) |
| `SingleKeywordData` | Dropdown | `KeywordNo` (int) + `DataValue` (string) |
| `MultipleKeywordData` | Multi-select | `Keywords[]` with `KeywordNo` + `DataValue` |
| `TableIndexData` | Table | `Rows[]` → `Values[]` with typed entries |

### GetDocument

Get document metadata (not index data — use GetDocumentIndexData for that).

```json
// Request:
{
  "DocNo": 265461,
  "IsAccessMaskNeeded": false
}
```

### PreprocessIndexData

Validate and preprocess index data before creating/updating a document.
Handles default values, calculated fields, auto-numbering, etc.

**IMPORTANT:** Items must be wrapped in an `IndexData` object, not passed directly.

```json
// Request:
{
  "CategoryNo": 8,
  "FillDependentFields": true,
  "ResetToDefaults": true,
  "DoCalculateFields": true,
  "GetAutoAppendIxData": false,
  "ExcludeReduntantForFillDependentFields": true,
  "IndexData": {
    "IndexDataItems": [
      {
        "StringIndexData": {
          "FieldNo": 101,
          "DataValue": "NEW-001"
        }
      }
    ]
  }
}

// Response:
{
  "IndexData": {
    "IndexDataItems": [...]
  }
}
```

Use `response["IndexData"]["IndexDataItems"]` as the items for the next step.

### EvaluateConditionalProperties

Check conditional field rules (visibility, mandatory status based on other field values).

```json
// Request:
{
  "CategoryNo": 8,
  "IndexDataItems": [...]
}

// Response:
{
  "ConditionalProperties": [...]
}
```

### CreateDocument

Create a new document with index data and optional file streams.
**Must be preceded by PreprocessIndexData and EvaluateConditionalProperties.**

```json
// Request:
{
  "TheDocument": {
    "IndexDataItems": [
      {
        "StringIndexData": {
          "FieldNo": 101,
          "DataValue": "NEW-001"
        }
      },
      {
        "SingleKeywordData": {
          "FieldNo": 105,
          "KeywordNo": 42
        }
      }
    ],
    "CategoryNo": 8,
    "Streams": [
      {
        "StreamNo": 0,
        "FileName": "invoice.pdf",
        "FileData": "<base64-encoded-content>"
      }
    ]
  }
}
```

**Important:** Keyword fields require `KeywordNo` (numeric ID), not the
display string. Use `GetKeywordsByFieldNo` to resolve keyword strings to numbers
(`GetDictionaryInfo` does not return per-field keyword lists).

### UpdateDocument2 (correct update endpoint)

Update index fields on an existing document.

**IMPORTANT:** The endpoint is `UpdateDocument2`, NOT `UpdateDocumentIndexData`.
Requires `LastChangeTime` or `LastChangeTimeISO8601` from the current document —
fetch via `GetDocumentIndexData` first, or the wrapper fetches it automatically.

```json
// Step 1: Get current document to obtain LastChangeTime
// POST GetDocumentIndexData {"DocNo": 265461}
// -> response["IndexData"]["LastChangeTime"] = "/Date(...)/"
// -> response["IndexData"]["LastChangeTimeISO8601"] = "2024-01-15T..."

// Step 2: Update
// POST UpdateDocument2
{
  "DocNo": 265461,
  "CheckInComments": "",
  "IndexData": {
    "IndexDataItems": [
      {
        "StringIndexData": {
          "FieldNo": 101,
          "DataValue": "UPDATED-VALUE"
        }
      }
    ],
    "DoFillDependentFields": true,
    "LastChangeTime": "/Date(1697760000000+0000)/",
    "LastChangeTimeISO8601": "2024-10-20T..."
  }
}
```

### GetDocumentStream

Download the binary file content for a document stream (e.g. the attached PDF/Word file).

```json
// Request:
{
  "DocNo": 265461,
  "StreamNo": 0
}

// Response:
{
  "DocNo": 265461,
  "StreamNo": 0,
  "FileName": "invoice.pdf",
  "FileData": [<byte array>]
}
```

**Notes:**
- `StreamNo`: 0 is the primary/main stream. Additional attachments use 1, 2, etc.
- `FileData` is a **raw byte array** in JSON responses (not base64). Cast directly to bytes:
  - Python: `bytes(result["FileData"])`
  - PowerShell: `[byte[]]$response.FileData`
- To list available streams for a document, call `GetDocument` — streams are listed in the response metadata.

---

### SaveDocumentIndexData

Alternative update endpoint (also requires `LastChangeTime`). Same request structure as
`UpdateDocument2` but wrapped in `SaveDocumentIndexData` endpoint.

### UpdateDocument

Update both index data AND streams simultaneously. Same `IndexData` structure with
`LastChangeTime`, plus optional `StreamsToUpdate`, `StreamNosToDelete`, `StreamsToRename`.

### GetDocumentHistory

Get version/change history for a document.

```json
// Request:
{"DocNo": 265461}
```

---

### Document Check-Out / Check-In

Verified against a live tenant 2026-07-16. `GetDocumentVersions` does **not** exist on the
live server (405) despite appearing in some client wrapper code — do not use it.

#### GetDocumentCheckoutStatus

```json
// Request:
{"DocNo": 265461}

// Response:
{
  "CheckOutStatus": {
    "CheckOutState": 0,
    "SomebodyElseName": ""
  }
}
```

`CheckOutState`: `0` = not checked out, `1` = checked out by the current caller. When
someone else holds the checkout, `SomebodyElseName` is populated with their name.

#### CheckOutDocument

```json
// Request:
{"DocNo": 265461}

// Response:
{
  "CheckOutSucceeded": true,
  "CurrentVersionNumber": 0,
  "SomebodyElseName": ""
}
```

#### CheckInDocument

Checking in requires the document to actually be "open" (i.e. have new content supplied,
e.g. via streams) — calling it with just `{"DocNo": ...}` and no changes fails:

```json
// Request that FAILS with no changes supplied:
{"DocNo": 265461}
// -> 500 InternalError: "The document file is not open."
```

The exact shape of a successful `CheckInDocument` payload (streams/index data) has not yet
been verified against a live tenant — treat as TODO before relying on it. If you don't need
to replace the file content, `UndoCheckOutDocument` is the safe way to release a checkout.

#### UndoCheckOutDocument

Releases a checkout without saving changes.

```json
// Request:
{"DocNo": 265461}

// Response: (empty object on success)
{}
```

---

### Comments

Verified against a live tenant 2026-07-16. Note the live API does **not** expose a
`GetComments` endpoint (despite some client wrapper naming) — the real endpoint is
`LoadComments`.

#### LoadComments

`ObjType` must be `2` for a document — `0` and `1` both fail with
`"Unsupported object type for comment"`.

```json
// Request:
{"ObjNo": 265461, "ObjType": 2, "MaxCount": 50}

// Response:
{
  "AllLoaded": true,
  "Comments": []
}
```

#### AddComment

Verified against a live tenant 2026-07-16.

```json
// Request:
{"ObjNo": 265461, "ObjType": 2, "CommentText": "Approved, ready to file"}

// Response: (empty on success)
{}
```

#### EditComment

Requires the comment's `ID` (a GUID string), returned by `LoadComments`.

```json
// Request:
{
  "ObjNo": 265461,
  "ObjType": 2,
  "ID": "3d2089e2-499d-452b-8d6b-80e557888506",
  "CommentText": "Approved, ready to file (edited)"
}

// Response: (empty on success)
{}
```

**Note:** There is no `DeleteComment` endpoint (confirmed absent from the live WSDL operation
list) — comments cannot be removed via the API, only added or edited.

---

### ExecuteFullTextQuery

Search document file content (not index fields) using full-text keywords.
Requires the Therefore full-text index to be enabled per-category
(`GetCategoryInfo`'s `IsFulltextEnabled`) and the document to actually be indexed —
see the pitfall below.

**IMPORTANT — the request shape below is verified against a live tenant 2026-07-16 and
differs from older docs/examples that show `SearchText`/`CategoryNo`.** The real request
requires `Search` (not `SearchText`), `Categories` (a plural array, not `CategoryNo`),
and `ContextMode`/`SearchScope`/`SortOrder` — omitting any of these causes a 500
`"...cannot be deserialized because the required data members ... were not found"`.

```json
// Request:
{
  "FullTextQuery": {
    "Search": "invoice urgent review",
    "Categories": [8],
    "MaxRows": 100,
    "BlockSize": 100,
    "CaseNo": 0,
    "ContextMaxSizeKB": 0,
    "ContextMode": 0,
    "FuzzySearchLevel": 0,
    "LCID": 0,
    "MaxContentChars": 0,
    "SearchScope": 0,
    "SortOrder": 0,
    "UseThesaurus": false
  },
  "IncludeIndexData": false
}

// Response:
{
  "Results": [
    {
      "DocNo": 265461,
      "CategoryNo": 8,
      "CategoryName": "Invoices",
      "Title": "Invoice 67307PAOP",
      "Extension": "|PDF|",
      "DocSize": 99004,
      "HitCount": 1,
      "MatchedWords": ["urgent"],
      "Relevance": 100,
      "Rank": 0,
      "Context": "",
      "Modified": "/Date(...)/",
      "ModifiedISO8601": "2026-...",
      "IndexData": null
    }
  ]
}
```

**Response shape does NOT match `ExecuteSingleQuery`** — there's no `QueryResult`/
`Columns`/`ResultRows`/`HasRemainingRows` wrapper, just a flat `Results` array. Each
result includes `MatchedWords` and a `Relevance` score, which regular index queries
don't have.

**Notes:**
- `Categories: []` (empty array) searches across all categories — confirmed working,
  not "search nothing."
- Results are synchronous and inline — no `QueryId`/pagination for the basic call
  (an async variant, `ExecuteAsyncFullTextQuery`, also exists but wasn't tested).
- `Search` supports boolean operators and phrase quoting: `"purchase order" AND approved`
  (untested against a live tenant — inherited from older docs, treat as unconfirmed).

---

## Users

### ExecuteUsersQuery

Look up users. (**Note:** `ResolveUserName` does not exist on the live server —
use `ExecuteUsersQuery` instead.)

Verified against a live tenant 2026-07-16: `{"Flags": 4}` (no `Query` filter) reliably
returns every regular named user. `{"Query": "*", "Flags": 5}` returned an empty list on
the same tenant — prefer `Flags: 4` for listing all users.

```json
// Request — list all users:
{"Flags": 4}

// Response:
{
  "Users": [
    {
      "UserId": 9,
      "UserName": "craig.mewett",
      "DisplayName": "craig.mewett",
      "SMTP": "craig.mewett@example.com",
      "Disabled": false,
      "UserType": 1,
      "GUID": "970B5D72-7E37-4D26-9AB5-382B709392B8"
    }
  ]
}
```

**Note:** AD/LDAP users always return `UserId: 0`. Use the username string
for identification instead of the numeric ID.

### GetObjects

Lists users and groups together (there is no dedicated `GetGroups` endpoint — that returns 405).

```json
// Request:
{"Flags": 0, "Type": 11}

// Response:
{
  "FolderList": [],
  "ItemList": [
    {"Data": 2, "ID": 1, "Name": "Administrators", "Guid": "...", "Flags": 0, "FolderNo": 0},
    {"Data": 1, "ID": 2, "Name": "Administrator", "Guid": "...", "Flags": 0, "FolderNo": 0}
  ]
}
```

Filter `ItemList` by `Data`: `1` = user, `2` = group, `3` = special system principal.
`ID` is the group's numeric ID — pass it as `GroupId` to `GetUsersFromGroup` (see below).

Verified against a live tenant 2026-07-16: adding `"PermType": 8` to the request body
(seen in some client wrapper code) made no observable difference to the result — the
plain `{"Flags": 0, "Type": 11}` body above is sufficient.

### GetUsersFromGroup

```json
// Request — by name:
{"GroupName": "Administrators"}

// Request — by numeric ID (alternative):
{"GroupId": 1}

// Response:
{"Users": [{"UserId": 2, "UserName": "Administrator", ...}]}
```

Verified against a live tenant 2026-07-16:
- `GroupName` (string) works.
- `GroupId` (the group's numeric `ID` from `GetObjects`) also works.
- `GroupNo` is **not** a valid parameter name — sending it returns a 500
  `"Could not find group matching the name provided: '' in domain: ''"` because the server
  falls back to an empty group-name lookup. It fails loudly, it does not silently ignore
  the parameter.
- An unrecognized group name (whether via `GroupName` or `GroupId`) returns a 500 WSError.

---

## Keywords

### GetKeywordsByFieldNo

Get keyword entries for a field by its field number. Use this to resolve
keyword display values to `KeywordNo` before creating/updating documents.

```json
// Request:
{
  "FieldNo": 105,
  "CategoryNo": 8,
  "ShowDeactivatedKeywords": false
}

// Response:
{
  "Keywords": [
    {"KeywordNo": 42, "KeywordName": "Approved"},
    {"KeywordNo": 43, "KeywordName": "Rejected"},
    {"KeywordNo": 44, "KeywordName": "Pending"}
  ]
}
```

### GetKeywordsByKeyDic

Get keywords by dictionary number (alternative to GetKeywordsByFieldNo).

```json
// Request:
{"KeyDicNo": 12, "MaxValues": 100}
```

### ValidateKeywords

Validate keyword string values against a field's dictionary.

```json
// Request:
{"FieldNo": 105, "KeywordsToValidate": ["Approved", "Unknown"]}
```

---

## Workflows

### ExecuteTaskInfoQuery

Get workflow tasks. (**Note:** `GetMyTasks` does not exist on the live server —
use `ExecuteTaskInfoQuery` instead.)

```json
// Request (empty = tasks for current user):
{}

// Request (tasks for a specific process):
{"ProcessNo": 3}

// Response:
{
  "TaskInfos": [
    {
      "TaskNo": 55123,
      "TaskName": "Approve Invoice",
      "ProcessName": "AP Approval",
      "ProcessNo": 3,
      "DocNo": 265461,
      "AssignedTo": "john.smith",
      "CreatedDate": "/Date(1697760000000+0000)/",
      "DueDate": "/Date(1698364800000+0000)/",
      "Exits": [
        {"ExitNo": 1, "ExitName": "Approve"},
        {"ExitNo": 2, "ExitName": "Reject"}
      ]
    }
  ]
}
```

### CompleteTask

Complete a workflow task (advance to next step using a named exit/transition).

```json
// Request:
{
  "TaskNo": 55123,
  "SelectedExitNo": 1,
  "Comment": "Approved — within budget"
}

// Response: (empty on success)
```

Use `ExecuteTaskInfoQuery` to get `TaskNo` and valid `ExitNo` values before calling.

---

## Cases

A **case** is a folder-like object defined by a **case definition** (`CaseDefNo`) that
groups documents from one or more categories, with its own index fields and history —
distinct from an ordinary document/category. Discover case definitions via
`GetCategoriesTree` — nodes with `ItemType: 3` (see pitfall #22); their `ItemNo` is the
`CaseDefNo`.

Full lifecycle verified against a live tenant 2026-07-16 (created and deleted a test case).

### GetCaseDefinition

Get the case definition's metadata: linked categories and index fields.

```json
// Request:
{"CaseDefinitionNo": 11}

// Response:
{
  "CaseDefinition": {
    "CaseDefNo": 11,
    "Categories": [
      {"CategoryNo": 154, "Name": "Test Category 1", "Title": "Test Category 1", ...}
    ],
    "Fields": [
      {"FieldNo": 3742, "Caption": "ID", ...}
    ]
  }
}
```

**Note:** the request parameter is `CaseDefinitionNo`, not `CaseDefNo` (despite the
response field being named `CaseDefNo`).

### Querying documents by case — `CaseDefinitionNo` in a Query object does NOT filter

`ExecuteSingleQuery`/`ExecuteAsyncSingleQuery`/`ExecuteAsyncMultiQuery`'s `Query` object
accepts a `CaseDefinitionNo` field, which looks like it should scope a search to a case's
documents the way `CategoryNo` scopes it to a category. Verified against a live tenant
2026-07-16 that it does not work that way:

- `CaseDefinitionNo` **without** `CategoryNo` 500s — the server tries to load it as a
  category ID and fails: `"Failed to load information from database: Category - ID=11"`.
- `CaseDefinitionNo` **together with** `CategoryNo` is silently ignored: the response's
  own `QueryResult.CaseDefinitionNo` comes back `0`, and the result set is identical to
  querying `CategoryNo` alone.

**There is no query-time filter for "documents belonging to this case."** To get case
documents, use `GetCaseDocuments` (returns `DocumentNos`, see below) — a separate,
non-query call — then fetch each document individually, or fall back to filtering by
`CategoryNo` (from `GetCaseDefinition`'s `Categories` list) if a query is what you need.

### CreateCase

```json
// Request:
{"CaseDefNo": 11}

// Response:
{
  "CaseNo": 92,
  "LastChangeTime": "/Date(1784202283132)/",
  "LastChangeTimeISO8601": "2026-07-16T11:44:43.1320000Z"
}
```

Only `CaseDefNo` is required to create an empty case — index field values can be set
afterward via `SaveCaseIndexData`/`SaveCaseIndexDataQuick` (not yet verified — presumed to
mirror `UpdateDocument2`'s `IndexData`/`LastChangeTime` pattern).

### GetCase

```json
// Request:
{"CaseNo": 92}

// Response:
{
  "Case": {
    "CaseDefinitionNo": 11,
    "CaseNo": 92,
    "CreatedByUser": "Craig Mewett",
    "CreatedByUserNo": 9,
    "CreatedOn": "/Date(...)/",
    "IsClosed": false,
    "IndexData": {
      "CategoryNo": 0,
      "CtgryName": "Referenced Case Test",
      "IndexDataItems": [...]
    }
  }
}
```

An unknown/deleted `CaseNo` returns a 500 `ObjectDoesNotExist` ("Case does not exist").

### GetCaseDocuments

```json
// Request:
{"CaseNo": 92}

// Response:
{"DocumentNos": [265461, 265462]}
```

**Untested caveat:** in live testing, calling `LinkCaseToDocument` (below) against a fresh
case returned `200 {}` (apparent success) but the linked `DocNo` did not subsequently
appear in `GetCaseDocuments`. The minimal `{"CaseNo", "DocNo"}` payload may be incomplete —
investigate further (e.g. a required `CategoryNo`/`FieldNo` pairing) before relying on this
for a real integration.

### GetCaseHistory / GetCaseHistory2

Identical shape in testing; `GetCaseHistory2` additionally returns `AllRowsLoaded` (likely
supports pagination for long-running cases, not yet verified).

```json
// Request:
{"CaseNo": 92}

// Response:
{
  "CaseHistory": [
    {
      "ActionDate": "/Date(...)/",
      "EntryType": 1,
      "UserName": "Craig Mewett",
      "UserNo": 9,
      "Text": "",
      "AdditionalInfo": "Referenced Case Test -"
    }
  ]
}
```

### LinkCaseToDocument / LinkCases / UnlinkCases

`LinkCaseToDocument` takes `{"CaseNo": N, "DocNo": N}` and returns `200 {}`, but see the
caveat under `GetCaseDocuments` above — the observable effect wasn't confirmed. `LinkCases`
and `UnlinkCases` (presumably linking one case to another) were not tested.

### CloseCase / ReopenCase / DeleteCase / RestoreDeletedCase

Not all tested individually, but `DeleteCase` is confirmed:

```json
// Request:
{"CaseNo": 92}

// Response: (empty on success)
{}
```

After deletion, `GetCase`/`GetCaseDocuments`/etc. against that `CaseNo` return a 500
`"The case has already been deleted from Therefore"` rather than `ObjectDoesNotExist`,
distinguishing "deleted" from "never existed". `RestoreDeletedCase` presumably reverses
this (not tested — no need arose since the delete confirmation was sufficient).

---

## Error Handling

Therefore returns errors as JSON with this structure:

```json
{
  "WSError": {
    "ErrorCode": -1073741604,
    "ErrorCodeHex": "0xC00000DC",
    "ErrorCodeString": "SyntaxError",
    "ErrorId": "abc123",
    "ErrorMessage": "Syntax error near = 584190",
    "ErrorSource": 1,
    "InnerErrorCode": -1073741824,
    "InnerErrorCodeHex": "0xC0000000"
  }
}
```

**Common errors:**

| ErrorCodeString | Meaning | Fix |
|-----------------|---------|-----|
| `SyntaxError` | Bad query condition | Check condition format (no `=` for exact match) |
| `2684354562` | Missing tenant | Add `TenantName` header |
| `ObjectNotFound` | Bad DocNo or CategoryNo | Verify the number exists |
| `AccessDenied` | No permission | Check user permissions |
| `InvalidArgument` | Wrong parameter type/name | Check parameter names and types |

**Python error handling:**
```python
try:
    result = client.post("ExecuteSingleQuery", query)
except requests.exceptions.HTTPError as e:
    error_body = e.response.json() if e.response.content else {}
    ws_error = error_body.get("WSError", {})
    print(f"Error [{ws_error.get('ErrorCodeString')}]: {ws_error.get('ErrorMessage')}")
```
