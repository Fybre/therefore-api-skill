# Therefore API — PowerShell Reference

PowerShell-specific patterns and gotchas for the Therefore REST API.
Read this alongside `api_endpoints.md` when generating PowerShell scripts.

---

## Client Setup

All requests are **POST**. Use `Invoke-RestMethod` with UTF-8 encoded bytes
so the `charset=utf-8` content-type is honoured correctly.

```powershell
function Invoke-ThereforePost {
    param(
        [string]    $BaseUrl,
        [string]    $Username,
        [string]    $Password,
        [string]    $TenantName,
        [string]    $Endpoint,
        [hashtable] $Body
    )

    $uri   = "$($BaseUrl.TrimEnd('/'))/$Endpoint"
    $json  = $Body | ConvertTo-Json -Depth 10
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)   # encode AFTER ConvertTo-Json

    $pair    = "$Username`:$Password"
    $b64     = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($pair))

    $headers = @{
        "Authorization" = "Basic $b64"
        "Content-Type"  = "application/json; charset=utf-8"  # charset required
        "Accept"        = "application/json"
    }
    if ($TenantName) { $headers["TenantName"] = $TenantName }

    return Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -Body $bytes
}
```

**Note:** The base URL passed to the helper should already include `/theservice/v0001/restun`.
Construct it once: `$BaseUrl = $Server.TrimEnd("/") + "/theservice/v0001/restun"`

---

## Reserved Variable: $Host

**NEVER use `$Host` as a parameter name.** It is a PowerShell automatic variable
(the console host object) and cannot be overwritten — the script will throw:

```
WriteError: Cannot overwrite variable Host because it is read-only or constant.
```

Use `$Server`, `$ThereforeServer`, or `$ServerUrl` instead.

---

## Interactive Password Prompt

Use `Read-Host -AsSecureString` and convert via `NetworkCredential`.
The `Marshal::SecureStringToBSTR` approach is unreliable across PS versions.

```powershell
# CORRECT — works on PS 5.1 and PS 7, all platforms
$securePassword = Read-Host "Password" -AsSecureString
$Password = [System.Net.NetworkCredential]::new('', $securePassword).Password

# AVOID — Marshal approach has cross-version issues
# $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
#                 [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword))
```

---

## Async Query — Correct Pagination Pattern

**This is the most critical pattern to get right.**

`ExecuteAsyncSingleQuery` returns the **first page of results in its own response**
(inside `QueryResult`), in addition to the `QueryId`. Do NOT ignore this and jump
straight to `GetNextSingleQueryRows` — you will miss all data when the result fits
in one page (the common case), because the subsequent call returns nothing.

### Correct pattern

```powershell
# 1. Start async query — response contains QueryId AND first page of results
$startResult = Invoke-ThereforePost -Endpoint "ExecuteAsyncSingleQuery" -Body @{
    Query = @{
        CategoryNo              = $CategoryNo
        Conditions              = @()
        SelectedFieldsNoOrNames = @("Reference", "Entity")
        MaxRows                 = 0        # 0 = unlimited
        RowBlockSize            = 200
        Mode                    = 0
    }
}

# NOTE: async returns QueryId (lowercase 'd')
$queryId = $startResult.QueryId

$allRows = [System.Collections.Generic.List[object]]::new()

try {
    # 2. Process the FIRST PAGE from the initial response — don't skip this
    #    $startResult.QueryResult contains ResultRows and Columns
    ProcessPage $startResult

    # 3. Fetch further pages only while more remain
    while ($startResult.HasRemainingRows -eq $true) {
        # NOTE: GetNextSingleQueryRows uses QueryID (uppercase 'D')
        $startResult = Invoke-ThereforePost -Endpoint "GetNextSingleQueryRows" -Body @{
            QueryID      = $queryId     # uppercase D here
            RowBlockSize = 200
        }
        ProcessPage $startResult
    }
}
finally {
    # 4. ALWAYS release — even on error
    # NOTE: ReleaseSingleQuery also uses QueryID (uppercase 'D')
    Invoke-ThereforePost -Endpoint "ReleaseSingleQuery" -Body @{ QueryID = $queryId }
}
```

### Wrong pattern (causes empty results for single-page queries)

```powershell
# WRONG — ignores first page in $startResult, goes straight to GetNextSingleQueryRows
$startResult = Invoke-ThereforePost -Endpoint "ExecuteAsyncSingleQuery" -Body $queryBody
$queryId = $startResult.QueryId

while ($hasMoreRows) {
    $page = Invoke-ThereforePost -Endpoint "GetNextSingleQueryRows" -Body @{
        QueryID = $queryId; RowBlockSize = 200
    }
    # ... process $page — misses all rows when they fit in the first response
}
```

### QueryId case sensitivity summary

| Endpoint | Field name | Case |
|----------|-----------|------|
| `ExecuteAsyncSingleQuery` response | `QueryId` | lowercase d |
| `GetNextSingleQueryRows` request | `QueryID` | uppercase D |
| `ReleaseSingleQuery` request | `QueryID` | uppercase D |

---

## Parsing Query Results

`Columns` and `IndexValues` are parallel arrays — always build the column map
from the `Columns` array rather than assuming field order.

```powershell
# Build column name -> index map from Columns array
$colIndexMap = @{}
$queryResult.Columns | ForEach-Object -Begin { $i = 0 } -Process {
    $name = if ($_.ColName) { $_.ColName } else { $_.Caption }
    $colIndexMap[$name] = $i
    $i++
}

# Extract a value by field name
foreach ($row in $queryResult.ResultRows) {
    $docNo = $row.DocNo                                    # always on the row object
    $ref   = $row.IndexValues[$colIndexMap["Reference"]]   # positional via map
}
```

**Note:** `DocNo` is always a direct property of each `ResultRow` object —
it is NOT in `IndexValues`, regardless of which fields are selected.

---

## Selecting Specific Fields

Pass field names in `SelectedFieldsNoOrNames`. An empty array returns all fields.
You can use either field names (strings) or field numbers (ints).

```powershell
# Named fields only
SelectedFieldsNoOrNames = @("Reference", "Entity", "Invoice_Date")

# All fields
SelectedFieldsNoOrNames = @()

# By field number
SelectedFieldsNoOrNames = @(491, 460)
```

The `Columns` array in the response will reflect the fields actually returned,
in the server's column order. Always derive column positions from `Columns`,
never hardcode them.

---

## Output Formats

```powershell
# Plain text — one value per line
$allRows | ForEach-Object { $_.DocNo.ToString() } | Set-Content -Path $file -Encoding UTF8

# CSV — use Export-Csv for automatic quoting
$csvRows = foreach ($row in $allRows) {
    [PSCustomObject][ordered]@{
        DocNo     = $row.DocNo
        Reference = $row.IndexValues[$colIndexMap["Reference"]]
        Entity    = $row.IndexValues[$colIndexMap["Entity"]]
    }
}
$csvRows | Export-Csv -Path $file -NoTypeInformation -Encoding UTF8
```

---

## No External Modules Required

All Therefore PowerShell scripts use only PowerShell built-ins and .NET standard
library. No `Install-Module` or `Import-Module` is needed. Compatible with PS 5.1+.

| Used | Source |
|------|--------|
| `Invoke-RestMethod` | Built-in (PS 3.0+) |
| `ConvertTo-Json` / `Export-Csv` / `Set-Content` | Built-in |
| `Read-Host` | Built-in |
| `[System.Net.NetworkCredential]` | .NET standard library |
| `[System.Text.Encoding]` / `[Convert]` | .NET standard library |
| `[System.Collections.Generic.List[object]]` | .NET standard library |
