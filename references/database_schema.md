# Therefore SQL Database Schema Reference (on-premises)

Derived from a full SSMS "Generate Scripts" export of an on-prem Therefore database
(SQL Server 2022, compat level 160; schema includes passkeys, webhooks and Graph connector
tables, so it is a recent release). 206 tables, ~300 indexes, ~140 foreign keys.

**Scope.** Only on-prem systems give SQL access — Therefore Online tenants do not. Use this to
*read and diagnose*; the REST API (or Solution Designer) remains the only supported way to
change anything.

Facts below are **confirmed** from the DDL unless marked *(inferred)* — inferred items need a
live check before you rely on them.

---

## 1. Ground rules

- **Read-only.** Never `INSERT`/`UPDATE`/`DELETE` Therefore tables. Writes bypass the server's
  object cache, number allocation (`TheActno1`/`TheActnoEP`, `TheCounter`), audit, full-text
  queue, workflow triggers and retention. Use `WITH (NOLOCK)` or a read replica for heavy
  reporting on a live system.
- **Sensitive tables** — don't dump or paste their contents: `TheCredentialStore.SecretEncrypted`,
  `TheUser.UserPwd`, `TheUserSync.UserPwd`, `TheGraphConn.ClientSecret`, `TheReplConn.EncPwd`,
  `TheSPConnection.Password`, `TheShareLink.Password`, `TheCloudStorage.AuthenticationInfo`,
  `TheDocDownloadProviders.AuthenticationXML`, `TheWebhooks.Secret`, `TheConnectToken.Token`,
  `ThePasskeys`. `TheWebhookLog.Payload` may contain full inbound payloads.
- **Customer tables can live in the same DB.** This export also had `tblOrders`,
  `Student_Lookup` and views `vw_OrdersChar`/`vw_OrdersInt` — sources for referenced-table
  fields or external lookups. Anything not prefixed `The` is customer-owned.

---

## 2. Naming conventions (the key to navigating any Therefore DB)

Object numbers in the REST API map directly onto physical table names:

| Physical table | Holds | Number comes from | API equivalent |
|---|---|---|---|
| `TheCat{CtgryNo}` | Index data for a category — **one row per document**, PK `DocNo`, one column per field | `TheCategory.CtgryNo` / `.TableName` | `CategoryNo` |
| `TheCase{CaseDefNo}` | Case header index data, PK `CaseNo` | `TheCaseDefinition.CaseDefNo` / `.TableName` | `CaseDefinitionNo` |
| `TheIxTable{FieldNo}` | Rows of a **table field**: `DocNo, RowNo, RowPosition`, then one column per sub-field. FK → its `TheCat` table | `TheCtgryFields.FieldNo` of the table field | `TableIndexData.FieldNo` |
| `TheKeywords{KeyDicNo}` | Keyword dictionary entries: `KeywordNo, Deleted, Id` only — **no text column** | `TheKeywordDics.KeyDicNo` / `.KeyDicTable` | `KeywordNo` |
| `TheRefTable{n}` / `TheRefTableTmp{n}` | Synced referenced-table data (+ staging copy) *(n is probably `TheDataType.TypeNo` — inferred)* | `TheDataType.TableName` | `GetReferencedTableInfo` |
| `TheCatLog`, `TheCatReport`, `TheCatSpool`, `TheCatTemplate` | Built-in system categories (logs, reports, spool files, templates) | — | — |

Example from the export: `TheIxTable1391` (`AI_Code, Reasoning, Confidence`) has FK → `TheCat39`,
i.e. field 1391 is a table field on category 39.

**Column names = `TheCtgryFields.FieldID`**, not the caption. API `ColName` / `FieldID` is the SQL
column. A field rename in the designer changes the caption, not necessarily the column.

---

## 3. Names, captions and keyword text live in `TheString`

Category, case definition, workflow process and task tables have **no name column**. All display
text is localised in one table:

```
TheString(MainObjType, MainObjNo, ObjNo, SubObjNo, VersionNo, LanguageID, StringType, LocalizedText)
```

Known codes (confirmed from the built-in functions):

| Object | MainObjType | MainObjNo | ObjNo | StringType |
|---|---|---|---|---|
| Category name | 3 | CtgryNo | 0 | 1 |
| Workflow process name | 19 | ProcessNo | 0 | 8 |
| Workflow task name | 19 | ProcessNo | TaskNo | 10 |
| Case definition name | 37 | CaseDefNo | 0 | 18 |

Language fallback order: client language → server language → `1033` (en-US) → anything.

Field captions and keyword display text are **not** in their own tables either, so they must also
be in `TheString` under other codes *(inferred)*. Discover the codes once per system:

```sql
SELECT MainObjType, StringType, COUNT(*) n, MIN(LocalizedText) sample
FROM TheString GROUP BY MainObjType, StringType ORDER BY 1, 2;
```

Use the shipped helpers rather than re-implementing the lookup (the `itvf_` versions are inline
table-valued and much faster in set queries than the scalar `fn_` versions):

```sql
SELECT c.CtgryNo, c.TableName, n.LocalizedText AS Name
FROM TheCategory c
CROSS APPLY dbo.itvf_TheGetCtgryNameFromNo(c.CtgryNo, 1033, 1033) n
ORDER BY c.CtgryNo;
```

Others: `itvf_TheGetCaseDefNameFromNo`, `itvf_TheGetWFProcessNameFromNo`,
`itvf_TheGetWFTaskNameFromID(@TaskId, …)`, `itvf_TheGetLocalizedText(…)`.

---

## 4. Core object model

### Documents and versions
- `TheDocument` — one row per document: **current** `VersionNo`, `IsDeleted` (soft delete →
  recycle bin), `CheckOutUserNo`/`CheckOutDate`/`CheckOutToCloud`, `RetentionProtection`,
  `Security`, `LastChangeTime`.
- `TheDocVersion` (PK `DocNo, VersionNo`) — per version: **`CtgryNo`** (a document's category is
  recorded per version), `StgFileID` (storage container), `FileCount`, `DocSize`,
  `CheckinComment`, `SubmissionNo` (→ the eForm submission that created it).
- `TheCat{n}` holds a single row per `DocNo`, so it reflects **current** index data only
  *(inferred: older versions' index values are not in the category table)*.
- Find a document's category: `SELECT CtgryNo FROM TheDocVersion v JOIN TheDocument d ON d.DocNo=v.DocNo AND d.VersionNo=v.VersionNo WHERE d.DocNo=@doc`.
- Deleted documents: `TheRecycleBin` (soft) and `TheTombstones` (hard delete record with
  `DeleteTime`, `CtgryNo`).

### Storage
`TheDocVersion.StgFileID → TheStorageFiles (MediaNo, BackMediaNo, Status, StgFileSize)
→ TheMedia → TheMediaPool → TheDevice → TheServer`. `TheStoragePolicy` (primary/backup pool)
is assigned per category (`TheCategory.StoragePolicyNo`). Dedup: `TheContentFiles.Hash` +
`TheContentRelations(ContentFileId, DocNo, VersionNo)`. Pending work queues:
`TheMigrate`, `TheDemigrate`, `TheRetentionQueue`, `TheFulltextQueue` (`RetryCount`, `DoNotRetry`).

### Categories and fields
- `TheCategory` — `TableName`, `CaseDefNo` (category belongs to a case definition),
  `WorkflowOnNew`/`WorkflowOnUpdate` (auto-start process), `NewVersionOnIxChange`,
  `CheckInMode`, `AutoApndMode`, `FulltextMode`, share-link defaults, `CtgryID` (string ID).
- `TheCtgryFields` — **one table for category fields, case-definition fields and
  query-template fields** (`CtgryNo` / `CaseDefNo` / `QueryTemplateNo`; one is set). Useful
  columns: `FieldID` (= SQL column), `TypeNo` → `TheDataType`, `Length`, `Scale`, `Mandatory`,
  `MustExist`, `RegularExpr`, `Formula`, `Condition`, `DefaultVal`, `CounterNo` → `TheCounter`,
  `BelongsTo` (sub-field → its table field), `ParentFNo`/`ShowInTabNo` (tab container),
  `ForeignTable`/`ForeignCol`, `DependencyMode`, `IndexType`, `FullTextSearch`, `Visible`.
- `TheDataType` — `TypeGroup` (1–8; maps to the API's index-data kinds *(mapping inferred)*),
  `TableName`/`IndexColumn` for referenced tables and keyword types, `WebServiceConfig`,
  `LastRun`/`LastRunError` (referenced-table sync status — handy when lookups go stale).
- `TheKeywordDics` — `KeyDicName`, `KeyDicTable`, `SingleTypeNo`/`MultTypeNo` (the data types a
  field uses for single/multi-select). Keyword foreign keys from category tables show which
  dictionary a field uses (e.g. `TheCat14.Area → TheKeywords10`).
- `TheDocTitles`/`TheDocTitleFields` — which fields build the document title per category/case.

### Cases
`TheCase` (header: `CaseDefNo`, `IsClosed`, `ClosedOn`, `IsDeleted`) + `TheCase{n}` (index data).
Documents link to a case by a **`CaseNo` column in their category table** (indexed `AXC{n}_CaseNo`),
not via a junction table. `TheDocCaseHistory` logs document/case events (`EventType`, `AddInfo`).

### Linked objects
`TheObjLinks(SrcTypeNo, SrcObjNo, DestTypeNo, DestObjNo)` — generic document/case links.
`TheAutomaticLinks` — field-to-field auto-link rules.

---

## 5. Workflow

| Table | Purpose |
|---|---|
| `TheWFProcesses` | Process: `Enabled`, `CtgryNo`/`CaseDefNo`, `ActiveVersion`, `ProcessID` |
| `TheWFProcessVersion` | Per version: `Settings` (XML), `NotifyOnError`, `DelFinishAfter`, `AttachHistory` |
| `TheWFTasks` | Tasks per process **version** (`TaskNo` unique; `TaskId` GUID stable across versions). `Type`, `Settings` (XML/JSON with task config), `ScriptName`, `AssignFromFieldNo`, `DueDateFromFieldNo` |
| `TheWFTransitions` | `TaskFromNo → TaskToNo`, `IsElse`, `OnOverdue`, `Settings` (conditions) |
| `TheWFInstances` | Running instances: process/version, `InitiatorNo`, start/due, `DeleteOn` |
| `TheWFTokens` | **Where each instance currently is**: `TaskNo`, `TaskStartDate`, `TaskDueDate`, `LastUserNo`, and **`ErrCode`/`ErrInfo`/`ErrTimeStamp`/`ErrCount`** for failed automatic tasks |
| `TheWFDocuments` | Documents/cases attached to an instance (`DocPos` 0 = main *(inferred)*) |
| `TheWFHistory` | Full history: `ActionDate`, `Type`, `UserNo`, `Text`, `TaskToNo` |
| `TheWFInstAccess` | Who can see/act on a token (`EntryType`, `UserNo`) |
| `TheWFQueue` | Documents waiting for a workflow start, with `IsError`/`ErrorText`/`RetryAt` |
| `TheReporting` | Workflow analytics events: durations, `IsOverdue`, `ExecDuration` |
| `TheWFChecklist`/`TheWFCLState`, `TheWFChoices` | Checklist items/state; user-choice assignment lists |

**Stuck / errored workflow triage:**
```sql
SELECT t.InstanceNo, t.TokenNo, p.LocalizedText AS Process, tn.LocalizedText AS Task,
       t.ErrCode, t.ErrInfo, t.ErrCount, t.ErrTimeStamp, d.DocNo
FROM TheWFTokens t
JOIN TheWFInstances i ON i.InstanceNo = t.InstanceNo
JOIN TheWFTasks k ON k.TaskNo = t.TaskNo
CROSS APPLY dbo.itvf_TheGetWFProcessNameFromNo(i.ProcessNo, 1033, 1033) p
OUTER APPLY dbo.itvf_TheGetLocalizedText(19, i.ProcessNo, t.TaskNo, 0, 1033, 1033, 10) tn
LEFT JOIN TheWFDocuments d ON d.InstanceNo = t.InstanceNo AND d.DocPos = 0
WHERE t.ErrCode IS NOT NULL OR t.ErrCount > 0
ORDER BY t.ErrTimeStamp DESC;

SELECT * FROM TheWFQueue WHERE IsError = 1;   -- documents that never started their workflow
```

---

## 6. Users, groups and security

- `TheUser` holds **users and groups** (`UserType` 1–4 — groups are a `UserType`, matching the
  API's `GetObjects` `Data==2` *(exact code-to-type mapping inferred)*). `Domain` + `Name` +
  `UserType` is unique; `ServiceAccount`, `Force2FA`, `Passkeys`, `Deleted` flags.
- `TheUserGroups(UserNo, GroupNo)` — **both FKs point to `TheUser`**.
- `TheDelegate` — absence delegation (`Active`).
- `TheRole.Permission` is a **bigint bitmask**; `DenyRole` marks deny roles.
- `TheRoleAssignments(ObjType, ObjNo, SubObjNo, UserNo, RoleNo, StopInheritance, Condition)` —
  every permission grant in the system; `Condition` = conditional (index-value-based) security.
  `ObjType` values match `GetObjects` Type codes *(inferred)*; folder inheritance via `TheFolder.ParentFolderNo`.
- `ThePortalAccess`, `TheUserSync` — portal users and their auto-sync rules (`ConditionXML`).
- `TheShareLink` (+`TheShareLinkAssignment`) — every share link, expiry, permission type.

Effective "who has access to category N":
```sql
SELECT ra.UserNo, u.Name, u.UserType, ra.RoleNo, r.Permission, r.DenyRole, ra.Condition
FROM TheRoleAssignments ra JOIN TheUser u ON u.UserNo = ra.UserNo JOIN TheRole r ON r.RoleNo = ra.RoleNo
WHERE ra.ObjNo = @CtgryNo;   -- confirm the category ObjType value first: SELECT DISTINCT ObjType FROM TheRoleAssignments
```

---

## 7. Settings — the key-name map the REST API doesn't give you

The skill's **Server Settings** section documents keys discovered by brute-force scanning.
On-prem, the table has the names:

```
TheSettings(SettingNo, ServerNo, SettingValue nvarchar(max), SettingName)
```

```sql
SELECT SettingNo, ServerNo, SettingName, LEFT(SettingValue, 200) AS Value
FROM TheSettings ORDER BY SettingNo, ServerNo;
```

- `SettingNo` = the REST `SettingKeys` integer. Export this once and the provisional key table
  in the skill can be replaced with real names.
- `ServerNo` → `TheServer`; the same key can exist per server (multi-server installs), with
  `0` presumably the global value *(inferred)*.
- Exclude or mask credential-like keys before sharing the output.

Other config tables: `TheSystemVariables` (named variables used in scripts/workflows),
`TheHolidays` (business-day calc for due dates), `TheUserSettings`, `TheLicInfo`/`TheLicItems`/
`TheLicTransCredits` (licence & credit consumption), `TheReservedLicPoints`.

---

## 8. Capture, indexing, eForms and integrations

| Area | Tables | Notes |
|---|---|---|
| eForms | `TheEForm` (PK `FormNo, VersionNo`; `FormDefinition` = Form.io JSON; `IndexingProfileNo`; `AnonymousAccessEnabled`; `FormID`), `TheEFormSubmission` (`Submission` JSON, `SubmissionType` 0–3) | Every form version is kept. Pull the definition straight from SQL to diff versions. `TheDocVersion.SubmissionNo` links a document back to its submission |
| Indexing profiles | `TheIndexingProfile` (`InitScript` = profile script, `ScriptLang`, `Filter`, `AutoAppendMode`), `TheIndexingAssignment` (per field: `Expression`, `CheckCondition`, `ErrorFallback`) | Where eForm → index-field mapping and scripts live |
| Shared scripts | `TheCommonScript` (`Script`, `ScriptLang`), `TheCommonScriptRelation` | Grep all scripts in one query: `SELECT Name, Script FROM TheCommonScript WHERE Script LIKE '%restun%'` (plain SQL uses `%`; Therefore API conditions use `*`) |
| Workflow scripts | `TheWFTasks.ScriptName` + `.Settings` | |
| Content Connector | `TheCntConnSource` (`Source`, `Polling`, `Disabled`), `TheCntConnJob`, **`TheCntConnError`** (per-file failures with `ErrorText`) | First stop when an import folder "isn't working" |
| Capture / scanning | `TheCaptProfile`, `TheCaptStep`, `TheCaptBarcode`, `TheCaptField`, `TheDataExtractor*`, `TheForm*`, `ThePreprocessor`, `TheMFPDevice`/`TheMFPSettings` | |
| Office / UC | `TheOfficeProfile`/`Action`/`Assignment`, `TheUCProfile`/`Action`/`Control`/`Mapping` | Office add-in profiles; Universal Connector screen-capture mappings |
| Microsoft Graph | `TheGraphConn` (tenant, client id, `Status`, `ErrorText`), `TheGraphConnCtgry`, `TheGraphConnQueue` (pending ops with errors), `TheGraphConnSync`, `TheGraphConnGroupSync` | M365/SharePoint sync health |
| Webhooks | `TheWebhooks` (`Actions`, `IpWhitelist`, `VerifySettings`, `LogPayload`), **`TheWebhookLog`** (`ReceivedUTC`, `SourceIp`, `Verified`, `Result`, `ErrorText`, `Payload`) | Inbound webhook debugging |
| Other | `TheSPProfile`/`TheSPConnection` (SharePoint), `TheSigningProviders`/`TheSigningStatus`/`TheSigningDocs` (e-signature), `ThePowerBiDataSet`/`Table`, `TheCloudStorage`, `TheDocDownloadProviders`, `TheReplConn`/`Table`/`Column` (DB replication), `TheSAPContRep`, `TheSCProcessor`, `TheDashboard`, `TheTreeView*`, `TheQuery*` (saved queries), `TheRetentionPolicy`/`TheRetentionCtgry` | |

---

## 9. Audit and activity

| Table | Contents |
|---|---|
| `TheAudit` | Operation log: `TStamp`, `Operation`, `RetCode`, `UserName`, `Node`, `DocNo`, `CtgryName`, `WFInstanceNo`, `AddInfo` |
| `TheAuditLog` | Index of archived audit log documents (`DocNo`, `Server`) |
| `TheLoginHistory` | Every login: `ClientType`, `ClientVersion`, `Node`, `IPAddress`, `ErrorCode` (failed logins ≠ 0) |
| `TheStatistics` | Per-operation stats incl. `Duration`, licence used |
| `TheUsageStats` | Per-user usage counters |
| `TheObjectLock` | Current design-object locks (who has a category/process open in Solution Designer) |

---

## 10. Starter queries

```sql
-- Category inventory with doc counts
SELECT c.CtgryNo, n.LocalizedText Name, c.TableName,
       (SELECT COUNT(*) FROM TheDocument d
        JOIN TheDocVersion v ON v.DocNo = d.DocNo AND v.VersionNo = d.VersionNo
        WHERE d.IsDeleted = 0 AND v.CtgryNo = c.CtgryNo) Docs
FROM TheCategory c
CROSS APPLY dbo.itvf_TheGetCtgryNameFromNo(c.CtgryNo,1033,1033) n
ORDER BY c.CtgryNo;

-- Field list for a category (FieldID = SQL column = API ColName)
SELECT f.FieldNo, f.FieldID, f.TypeNo, t.Name TypeName, t.TypeGroup, f.Length, f.Mandatory,
       f.BelongsTo, f.CounterNo, f.Formula, f.RegularExpr
FROM TheCtgryFields f JOIN TheDataType t ON t.TypeNo = f.TypeNo
WHERE f.CtgryNo = @CtgryNo ORDER BY f.TabOrderPos;

-- Table fields and their physical tables
SELECT f.CtgryNo, f.FieldNo, f.FieldID, 'TheIxTable' + CAST(f.FieldNo AS varchar) PhysTable
FROM TheCtgryFields f
WHERE EXISTS (SELECT 1 FROM TheCtgryFields s WHERE s.BelongsTo = f.FieldNo);

-- Group membership
SELECT g.Name GroupName, u.Name UserName
FROM TheUserGroups ug JOIN TheUser g ON g.UserNo = ug.GroupNo JOIN TheUser u ON u.UserNo = ug.UserNo
ORDER BY g.Name, u.Name;

-- Failed logins in the last 7 days
SELECT TOP 200 h.Timestamp, u.Name, h.IPAddress, h.Node, h.ErrorCode
FROM TheLoginHistory h JOIN TheUser u ON u.UserNo = h.UserNo
WHERE h.ErrorCode <> 0 AND h.Timestamp > DATEADD(day,-7,SYSUTCDATETIME()) ORDER BY h.Timestamp DESC;

-- Content Connector errors
SELECT s.Name Source, e.FileName, e.TStamp, e.Status, LEFT(e.ErrorText,300) Err
FROM TheCntConnError e JOIN TheCntConnSource s ON s.CntConnSourceNo = e.CntConnSourceNo
ORDER BY e.TStamp DESC;
```

---

## 11. Open items to verify on a live system

1. `TheString` MainObjType/StringType for field captions and keyword text.
2. `TheDataType.TypeGroup` → API index-data type mapping.
3. `TheUser.UserType` values (user / group / portal / service?).
4. `TheRoleAssignments.ObjType` codes vs `GetObjects` Type codes; `TheRole.Permission` bit meanings.
5. Whether `TheRefTable{n}` uses the data type `TypeNo`.
6. Meaning of `TheWFTasks.Type` values and `TheWFDocuments.DocPos` 0.
7. Whether `TheSettings.ServerNo = 0` is the global row.
