# Therefore API — Python Examples

Complete, working Python patterns for common Therefore operations.
All examples use `requests` with a session configured per the SKILL.md auth section.

## Reusable Client Class

```python
import requests
from urllib.parse import urlparse
from typing import List, Dict, Optional

class ThereforeClient:
    """Minimal Therefore REST API client."""

    def __init__(self, base_url: str, username: str, password: str, tenant: str = None):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.endswith('/restun'):
            self.base_url += '/restun'

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({
            'Content-Type': 'application/json; charset=utf-8'
        })

        # Auto-detect tenant for Therefore Online
        if not tenant:
            parsed = urlparse(base_url)
            if 'thereforeonline.com' in (parsed.hostname or ''):
                tenant = parsed.hostname.split('.')[0]
        if tenant:
            self.session.headers.update({'TenantName': tenant})

    def post(self, endpoint: str, payload: dict = None) -> dict:
        url = f"{self.base_url}/{endpoint}"
        resp = self.session.post(url, json=payload or {}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def test_connection(self) -> bool:
        try:
            result = self.post("GetConnectionToken")
            return bool(result.get("Token"))
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
```

## Search Documents by Field Value (Synchronous)

```python
def search_by_field(client, category_no: int, field_name: str,
                    field_value: str, return_fields: List[str] = None) -> List[Dict]:
    """Search for documents where a field matches a value exactly."""

    query = {
        "Query": {
            "CategoryNo": category_no,
            "Conditions": [
                {"FieldNoOrName": field_name, "Condition": field_value}
            ],
            "MaxRows": 0,
            "RowBlockSize": 200,
            "Mode": 0
        }
    }
    if return_fields:
        query["Query"]["SelectedFieldsNoOrNames"] = return_fields

    result = client.post("ExecuteSingleQuery", query)
    query_result = result.get("QueryResult", {})

    # Build column map
    columns = query_result.get("Columns", [])
    col_map = {i: col.get("ColName") or col.get("Caption")
               for i, col in enumerate(columns)}

    # Parse rows
    documents = []
    for row in query_result.get("ResultRows", []):
        doc = {"DocNo": row["DocNo"], "VersionNo": row.get("VersionNo")}
        for i, val in enumerate(row.get("IndexValues", [])):
            if i in col_map:
                doc[col_map[i]] = val
        documents.append(doc)

    return documents


# Usage:
client = ThereforeClient("https://acme.thereforeonline.com/theservice/v0001",
                          "user", "pass")

docs = search_by_field(client, category_no=8,
                       field_name="Invoice_No", field_value="67307PAOP",
                       return_fields=["Invoice_No", "Supplier_Name"])

for doc in docs:
    print(f"DocNo={doc['DocNo']}, Invoice={doc.get('Invoice_No')}")
```

## Search Documents (Async — Preferred for Production)

```python
def search_by_field_async(client, category_no: int, field_name: str,
                          field_value: str, return_fields: List[str] = None,
                          row_block_size: int = 200) -> List[Dict]:
    """Search using ExecuteAsyncSingleQuery (preferred endpoint)."""

    query = {
        "Query": {
            "CategoryNo": category_no,
            "Conditions": [
                {"FieldNoOrName": field_name, "Condition": field_value}
            ],
            "MaxRows": 0,
            "RowBlockSize": row_block_size,
            "Mode": 0
        }
    }
    if return_fields:
        query["Query"]["SelectedFieldsNoOrNames"] = return_fields

    # Start async query — returns QueryId (lowercase 'd') AND first page of results
    result = client.post("ExecuteAsyncSingleQuery", query)
    query_id = result.get("QueryId")  # NOTE: lowercase 'd'

    if not query_id:
        return []

    col_map = {}
    all_rows = []

    def process_page(page):
        nonlocal col_map
        query_result = page.get("QueryResult", {})
        if not col_map:
            columns = query_result.get("Columns", [])
            col_map = {i: col.get("ColName") or col.get("Caption")
                       for i, col in enumerate(columns)}
        all_rows.extend(query_result.get("ResultRows", []))

    try:
        # CRITICAL: ExecuteAsyncSingleQuery returns the FIRST PAGE in its own response.
        # Do NOT skip straight to GetNextSingleQueryRows — when all results fit in one
        # page (the common case), GetNextSingleQueryRows returns nothing and all data
        # is lost. Always process the initial response first.
        process_page(result)

        # Fetch further pages only while more remain
        while result.get("HasRemainingRows"):
            result = client.post("GetNextSingleQueryRows", {
                "QueryID": query_id, "RowBlockSize": row_block_size
            })
            process_page(result)
    finally:
        # ALWAYS release the query
        try:
            client.post("ReleaseSingleQuery", {"QueryID": query_id})
        except Exception:
            pass

    # Parse rows
    documents = []
    for row in all_rows:
        doc = {"DocNo": row["DocNo"], "VersionNo": row.get("VersionNo")}
        for i, val in enumerate(row.get("IndexValues", [])):
            if i in col_map:
                doc[col_map[i]] = val
        documents.append(doc)

    return documents
```

## Get Full Document Index Data

```python
def get_index_data(client, doc_no: int) -> Dict:
    """Get all index fields for a document."""
    return client.post("GetDocumentIndexData", {"DocNo": doc_no})


def get_field_value(index_data: dict, field_name: str) -> Optional[str]:
    """Extract a named field from GetDocumentIndexData response."""
    items = index_data.get("IndexData", {}).get("IndexDataItems", [])
    for item in items:
        for type_key, data in item.items():
            if isinstance(data, dict) and data.get("FieldName") == field_name:
                return str(data.get("DataValue", ""))
    return None


def get_all_fields(index_data: dict) -> Dict[str, str]:
    """Extract all fields as a flat dict from GetDocumentIndexData response."""
    fields = {}
    items = index_data.get("IndexData", {}).get("IndexDataItems", [])
    for item in items:
        for type_key, data in item.items():
            if isinstance(data, dict) and "FieldName" in data:
                fields[data["FieldName"]] = str(data.get("DataValue", ""))
    return fields


# Usage:
index_data = get_index_data(client, doc_no=265461)
invoice = get_field_value(index_data, "Invoice_No")
all_fields = get_all_fields(index_data)
print(all_fields)
```

## Paginated Query (All Results)

```python
def search_all(client, category_no: int, conditions: List[Dict],
               return_fields: List[str] = None,
               row_block_size: int = 500) -> List[Dict]:
    """Execute an async query and fetch ALL result pages."""

    query = {
        "Query": {
            "CategoryNo": category_no,
            "Conditions": conditions,
            "MaxRows": 0,
            "RowBlockSize": row_block_size,
            "Mode": 0
        }
    }
    if return_fields:
        query["Query"]["SelectedFieldsNoOrNames"] = return_fields

    # Use async endpoint (preferred)
    # IMPORTANT: ExecuteAsyncSingleQuery returns the FIRST PAGE in its own response.
    # Process it before calling GetNextSingleQueryRows (see SKILL.md pitfall #17).
    result = client.post("ExecuteAsyncSingleQuery", query)
    query_id = result.get("QueryId")  # lowercase 'd'

    if not query_id:
        return []

    col_map = {}
    all_rows = []

    def process_page(page):
        nonlocal col_map
        query_result = page.get("QueryResult", {})
        if not col_map:
            columns = query_result.get("Columns", [])
            col_map = {i: col.get("ColName") or col.get("Caption")
                       for i, col in enumerate(columns)}
        all_rows.extend(query_result.get("ResultRows", []))

    try:
        process_page(result)  # First page is in the initial response
        while result.get("HasRemainingRows"):
            result = client.post("GetNextSingleQueryRows", {
                "QueryID": query_id, "RowBlockSize": row_block_size
            })
            process_page(result)
    finally:
        try:
            client.post("ReleaseSingleQuery", {"QueryID": query_id})
        except Exception:
            pass

    # Parse all rows
    documents = []
    for row in all_rows:
        doc = {"DocNo": row["DocNo"]}
        for i, val in enumerate(row.get("IndexValues", [])):
            if i in col_map:
                doc[col_map[i]] = val
        documents.append(doc)

    return documents


# Usage — get all invoices over $1000:
docs = search_all(client, category_no=8,
                  conditions=[{"FieldNoOrName": "Amount", "Condition": ">= 1000"}],
                  return_fields=["Invoice_No", "Amount", "Supplier_Name"])
```

## Get Category Info and Validate Fields

```python
def get_category_fields(client, category_no: int) -> List[str]:
    """Get list of field names for a category."""
    info = client.post("GetCategoryInfo", {
        "CategoryNo": category_no,
        "IsAccessMaskNeeded": False,
        "IsSearchFieldOrderNeeded": False
    })
    return [f.get("Caption", "") for f in info.get("CategoryFields", [])]


# Usage:
fields = get_category_fields(client, 8)
print(f"Category fields: {fields}")

# Validate before querying:
if "Invoice_No" not in fields:
    print("WARNING: Invoice_No field not found in category!")
```

## Multi-Condition Query

```python
# Search with multiple conditions (AND logic):
conditions = [
    {"FieldNoOrName": "Status", "Condition": "Approved"},
    {"FieldNoOrName": "Supplier_Name", "Condition": "LIKE Acme%"},
    {"FieldNoOrName": "Amount", "Condition": ">= 500"}
]

docs = search_all(client, category_no=8, conditions=conditions,
                  return_fields=["Invoice_No", "Supplier_Name", "Amount", "Status"])
```

## IS NULL / IS NOT NULL Queries

```python
# Find documents where a field is empty:
docs = search_all(client, category_no=8,
                  conditions=[{"FieldNoOrName": "Notes", "Condition": "IS NULL"}])

# Find documents where a field has a value:
docs = search_all(client, category_no=8,
                  conditions=[{"FieldNoOrName": "Notes", "Condition": "IS NOT NULL"}])
```

## Sorted Query

```python
# Search with sorting:
query = {
    "Query": {
        "CategoryNo": 8,
        "Conditions": [
            {"FieldNoOrName": "Status", "Condition": "Approved"}
        ],
        "SelectedFieldsNoOrNames": ["Invoice_No", "Amount"],
        "OrderByFieldsNoOrNames": ["Amount"],
        "MaxRows": 0,
        "RowBlockSize": 200,
        "Mode": 0
    }
}
result = client.post("ExecuteSingleQuery", query)
```

## Document Creation (Full Workflow)

```python
import base64

def create_document(client, category_no: int, index_items: List[Dict],
                    file_path: str = None) -> int:
    """Create a document with the full 4-step workflow."""

    # Step 1: Get category info (for validation)
    cat_info = client.post("GetCategoryInfo", {
        "CategoryNo": category_no,
        "IsAccessMaskNeeded": False,
        "IsSearchFieldOrderNeeded": False
    })

    # Step 2: Preprocess index data
    preprocessed = client.post("PreprocessIndexData", {
        "CategoryNo": category_no,
        "IndexData": {"IndexDataItems": index_items}  # Must be wrapped in IndexData — see SKILL.md pitfall #13
    })
    processed_items = preprocessed.get("IndexData", {}).get("IndexDataItems", index_items)

    # Step 3: Evaluate conditional properties
    client.post("EvaluateConditionalProperties", {
        "CategoryNo": category_no,
        "IndexDataItems": processed_items
    })

    # Step 4: Create document
    doc_payload = {
        "TheDocument": {
            "IndexDataItems": processed_items,
            "CategoryNo": category_no,
            "Streams": []
        }
    }

    # Attach file if provided
    if file_path:
        with open(file_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode("utf-8")
        doc_payload["TheDocument"]["Streams"].append({
            "StreamNo": 0,
            "FileName": file_path.split("/")[-1],
            "FileData": file_data
        })

    result = client.post("CreateDocument", doc_payload)
    return result.get("DocNo")


# Usage:
new_doc_no = create_document(client, category_no=8, index_items=[
    {"StringIndexData": {"FieldNo": 101, "DataValue": "INV-2024-001"}},
    {"MoneyIndexData": {"FieldNo": 103, "DataValue": 1500.00}},
], file_path="/path/to/invoice.pdf")

print(f"Created document: {new_doc_no}")
```

## Error Handling Pattern

```python
def safe_search(client, category_no, field_name, field_value):
    """Search with proper error handling."""
    try:
        return search_by_field(client, category_no, field_name, field_value)
    except requests.exceptions.HTTPError as e:
        error_body = e.response.json() if e.response.content else {}
        ws_error = error_body.get("WSError", {})
        error_msg = ws_error.get("ErrorMessage", str(e))
        error_code = ws_error.get("ErrorCodeString", "")
        print(f"Therefore error [{error_code}]: {error_msg}")
        return []
    except requests.exceptions.ConnectionError:
        print("Cannot connect to Therefore server")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []
```

## Full Working Script Template

```python
#!/usr/bin/env python3
"""Template for Therefore API scripts."""

import requests
from urllib.parse import urlparse

# Configuration
URL = "https://acme.thereforeonline.com/theservice/v0001"
USERNAME = "your_username"
PASSWORD = "your_password"
CATEGORY_NO = 8

def main():
    # Connect
    client = ThereforeClient(URL, USERNAME, PASSWORD)
    if not client.test_connection():
        print("Failed to connect!")
        return

    # Verify category
    fields = get_category_fields(client, CATEGORY_NO)
    print(f"Category has {len(fields)} fields: {', '.join(fields)}")

    # Search (using async endpoint)
    docs = search_by_field_async(client, CATEGORY_NO,
                                 "Invoice_No", "67307PAOP",
                                 return_fields=["Invoice_No", "Supplier_Name"])

    for doc in docs:
        print(f"Found: DocNo={doc['DocNo']}")

        # Get full details if needed
        index_data = get_index_data(client, doc['DocNo'])
        all_fields = get_all_fields(index_data)
        for name, value in all_fields.items():
            print(f"  {name}: {value}")

if __name__ == '__main__':
    main()
```

---

## MCP ThereforeClient Wrapper (src/therefore_client.py)

The `therefore-mcp` project ships a `ThereforeClient` wrapper class in `src/therefore_client.py`
that provides a higher-level Python API over the raw REST calls. If this library is available,
use it instead of writing raw `requests` calls.

### Setup

```python
import sys
sys.path.insert(0, 'src')
from therefore_client import ThereforeClient

client = ThereforeClient(
    base_url="https://demo.thereforeonline.com/theservice/v0001/restun",
    username="your_username",
    password="your_password"
)
```

Note: The wrapper takes the full `/restun` URL, unlike the raw client which appends it automatically.

### Wrapper Method Reference

| Wrapper Method | Underlying REST Endpoint |
|----------------|--------------------------|
| `client.get_document(doc_no, include_index_data)` | `GetDocumentIndexData` / `GetDocument` |
| `client.get_category_info(category_no)` | `GetCategoryInfo` |
| `client.execute_single_query(query)` | `ExecuteSingleQuery` |
| `client.create_document(category_no, streams, index_data_items, ...)` | `CreateDocument` |
| `ThereforeClient.make_stream_from_text(filename, content)` | (helper, no API call) |

### Check if Document Exists

```python
def document_exists(client, doc_no):
    try:
        doc = client.get_document(doc_no, include_index_data=False)
        return doc is not None
    except Exception as e:
        if "not found" in str(e).lower():
            return False
        raise
```

### Query with WhereClause (Wrapper Style)

The wrapper's `execute_single_query` accepts a `WhereClause` using SQL-style
column name syntax `[ColName] = 'value'` rather than the raw API's `Conditions` array:

```python
# Wrapper style — uses WhereClause with [ColName] syntax:
query = {
    "CategoryNo": category_no,
    "WhereClause": f"[InvoiceNumber] = '{invoice_no}'",
    "MaxRows": 1
}
result = client.execute_single_query(query)
rows = result.get("IndexDataRows", [])

# Raw REST style (equivalent) — uses Conditions array:
query = {
    "Query": {
        "CategoryNo": category_no,
        "Conditions": [{"FieldNoOrName": "InvoiceNumber", "Condition": invoice_no}],
        "MaxRows": 1,
        "RowBlockSize": 200,
        "Mode": 0
    }
}
result = client.post("ExecuteSingleQuery", query)
rows = result.get("QueryResult", {}).get("ResultRows", [])
```

### Index Data Structure (Wrapper vs Raw)

The wrapper uses a different index data structure for creating documents
than the raw API response format:

```python
# WRAPPER style — for create_document():
index_data_items = [
    {"Name": "Invoice_No",   "Value": {"StringIndexData": {"Value": "INV-001"}}},
    {"Name": "Invoice_Date", "Value": {"DateIndexData":   {"Value": "2024-02-17"}}},
    {"Name": "Amount",       "Value": {"MoneyIndexData":  {"Value": 1500.00}}},
    {"Name": "Status",       "Value": {"KeywordIndexData": {"KeywordName": "Approved"}}}
]

# RAW API style — for CreateDocument endpoint:
index_data_items = [
    {"StringIndexData": {"FieldNo": 101, "DataValue": "INV-001"}},
    {"DateIndexData":   {"FieldNo": 106, "DataValue": "2024-02-17"}},
    {"MoneyIndexData":  {"FieldNo": 103, "DataValue": 1500.00}},
    {"SingleKeywordData": {"FieldNo": 105, "KeywordNo": 42}}  # needs KeywordNo not name
]
```

**Key difference:** The wrapper uses `Name` (field name string) and `Value.TypeData.Value`,
while the raw API uses typed root keys with `FieldNo`/`FieldName` and `DataValue`.

### Reading Index Data (Wrapper vs Raw)

```python
# WRAPPER — get_document returns IndexDataDef + IndexDataItems paired:
doc = client.get_document(doc_no, include_index_data=True)
for field_def, value_item in zip(doc['IndexDataDef'], doc['IndexData']['IndexDataItems']):
    field_name = field_def['Name']
    field_type = field_def['TypeNo']
    if field_type == 0:   # String
        value = value_item.get('Value', {}).get('StringIndexData', {}).get('Value')
    elif field_type == 6: # Keyword
        value = value_item.get('Value', {}).get('KeywordIndexData', {}).get('KeywordName')

# RAW API — GetDocumentIndexData returns typed items with FieldName:
index_data = client.post("GetDocumentIndexData", {"DocNo": doc_no})
for item in index_data["IndexData"]["IndexDataItems"]:
    for type_key, data in item.items():
        if isinstance(data, dict):
            field_name = data.get("FieldName")
            value = data.get("DataValue")  # or KeywordNo for SingleKeywordData
```

### Create Document with File (Wrapper Style)

```python
import base64

# Build streams
with open("invoice.pdf", "rb") as f:
    file_data = base64.b64encode(f.read()).decode("ascii")

streams = [{
    "FileName": "invoice.pdf",
    "FileDataBase64JSON": file_data,
    "NewStreamInsertMode": 0
}]

# Or use the helper for text files:
streams = [ThereforeClient.make_stream_from_text("note.txt", "Document content here")]

# Create
result = client.create_document(
    category_no=8,
    streams=streams,
    index_data_items=index_data_items,  # wrapper-style items (see above)
    check_in_comments="Imported from XML batch"
)
new_doc_no = result.get("DocNo")
```

### Batch Document Check (Efficient)

Query multiple DocNos in a single API call rather than one call per document:

```python
def batch_check_documents(client, category_no, doc_nos):
    """Check which doc numbers exist — one query instead of N API calls."""
    if not doc_nos:
        return {}
    doc_nos_str = ','.join(str(n) for n in doc_nos)
    query = {
        "CategoryNo": category_no,  # Required
        "WhereClause": f"[DocNo] IN ({doc_nos_str})",
        "MaxRows": len(doc_nos)
    }
    result = client.execute_single_query(query)
    rows = result.get("IndexDataRows", [])
    return {row["IndexValues"][0]: row for row in rows}

# Usage:
found = batch_check_documents(client, category_no=8, doc_nos=list(range(10000, 11000)))
print(f"Found {len(found)} out of 1000 documents")
```

---

## WCF Date Format Utilities

Therefore stores dates as WCF JSON date strings: `/Date(milliseconds+offset)/`.
These helpers convert between WCF format and Python `datetime`.

```python
import re
from datetime import datetime, timezone, timedelta

def wcf_to_datetime(wcf_str: str) -> datetime:
    """Parse a WCF date string like /Date(1697760000000+0000)/ to datetime (UTC)."""
    if not wcf_str:
        return None
    m = re.match(r"/Date\((-?\d+)([+-]\d{4})?\)/", wcf_str)
    if not m:
        raise ValueError(f"Not a WCF date: {wcf_str!r}")
    ms = int(m.group(1))
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def datetime_to_wcf(dt: datetime) -> str:
    """Convert a datetime to WCF format (always UTC offset +0000)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    return f"/Date({ms}+0000)/"


def wcf_to_date_str(wcf_str: str) -> str:
    """Convert WCF date to YYYY-MM-DD string for display or query conditions."""
    dt = wcf_to_datetime(wcf_str)
    return dt.strftime("%Y-%m-%d") if dt else ""


# Usage:
index_data = get_index_data(client, doc_no=265461)
raw_date = get_field_value(index_data, "Invoice_Date")   # "/Date(1697760000000+0000)/"
dt = wcf_to_datetime(raw_date)
print(f"Invoice date: {dt.date()}")                       # 2023-10-20

# Build a date range query condition:
from_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
to_dt   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
conditions = [
    {"FieldNoOrName": "Invoice_Date", "Condition": f">= {from_dt.strftime('%Y-%m-%d')}"},
    {"FieldNoOrName": "Invoice_Date", "Condition": f"<= {to_dt.strftime('%Y-%m-%d')}"},
]
```

---

## Index Data Builder Helpers

Factory functions for building typed `IndexDataItems` entries.
Use these to construct index data for `PreprocessIndexData` and `CreateDocument`.

```python
from datetime import datetime, timezone
from typing import Union

def str_field(field_no: int, value: str) -> dict:
    """String field."""
    return {"StringIndexData": {"FieldNo": field_no, "DataValue": value}}

def int_field(field_no: int, value: int) -> dict:
    """Integer field."""
    return {"IntIndexData": {"FieldNo": field_no, "DataValue": value}}

def money_field(field_no: int, value: float) -> dict:
    """Money/currency field."""
    return {"MoneyIndexData": {"FieldNo": field_no, "DataValue": value}}

def date_field(field_no: int, value: Union[str, datetime]) -> dict:
    """Date field. Accepts YYYY-MM-DD string or datetime object."""
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d")
    return {"DateIndexData": {"FieldNo": field_no, "DataValue": value}}

def datetime_field(field_no: int, value: Union[str, datetime]) -> dict:
    """DateTime field. Accepts ISO string or datetime object."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = datetime_to_wcf(value)
    return {"DateTimeIndexData": {"FieldNo": field_no, "DataValue": value}}

def keyword_field(field_no: int, keyword_no: int) -> dict:
    """Single keyword field — requires numeric KeywordNo, not display string."""
    return {"SingleKeywordData": {"FieldNo": field_no, "KeywordNo": keyword_no}}

def bool_field(field_no: int, value: bool) -> dict:
    """Logical/boolean field."""
    return {"LogicalIndexData": {"FieldNo": field_no, "DataValue": value}}


def resolve_keyword(client, category_no: int, field_no: int, display_name: str) -> int:
    """Look up KeywordNo by display name for a given field."""
    result = client.post("GetKeywordsByFieldNo", {
        "FieldNo": field_no,
        "CategoryNo": category_no,
        "ShowDeactivatedKeywords": False
    })
    for kw in result.get("Keywords", []):
        if kw.get("KeywordName", "").lower() == display_name.lower():
            return kw["KeywordNo"]
    raise ValueError(f"Keyword '{display_name}' not found for field {field_no}")


# Usage:
status_kw_no = resolve_keyword(client, category_no=8, field_no=105, display_name="Approved")

index_items = [
    str_field(101, "INV-2024-001"),
    money_field(103, 1500.00),
    date_field(106, "2024-10-20"),
    keyword_field(105, status_kw_no),
]

new_doc_no = create_document(client, category_no=8, index_items=index_items,
                             file_path="/path/to/invoice.pdf")
```

---

## Download Document File (GetDocumentStream)

Retrieve the binary file content for a document stream (e.g. the attached PDF).

```python
import base64

def get_document_stream(client, doc_no: int, stream_no: int = 0) -> bytes:
    """Download a document stream and return raw bytes."""
    result = client.post("GetDocumentStream", {
        "DocNo": doc_no,
        "StreamNo": stream_no
    })
    b64 = result.get("FileDataBase64JSON") or result.get("FileData", "")
    return base64.b64decode(b64) if b64 else b""


def save_document_stream(client, doc_no: int, output_path: str,
                         stream_no: int = 0) -> int:
    """Download a document stream and save to disk. Returns file size."""
    data = get_document_stream(client, doc_no, stream_no)
    with open(output_path, "wb") as f:
        f.write(data)
    return len(data)


# Usage:
# Download the main PDF attached to a document
save_document_stream(client, doc_no=265461, output_path="/tmp/invoice_265461.pdf")

# Or download to memory and inspect:
raw = get_document_stream(client, doc_no=265461)
print(f"File size: {len(raw):,} bytes")

# To find out which streams exist, check GetDocumentIndexData:
index_data = get_index_data(client, doc_no=265461)
# stream_no=0 is the primary stream; additional streams have higher numbers
```

---

## Configuration and Environment Setup

Recommended pattern for configuring Therefore credentials from environment variables
or a `.env` file, keeping secrets out of source code.

```python
import os
import requests
from urllib.parse import urlparse
from typing import Optional
from dataclasses import dataclass

@dataclass
class ThereforeConfig:
    """Therefore connection configuration."""
    server_url: str          # e.g. https://acme.thereforeonline.com/theservice/v0001
    username: str
    password: str
    tenant: Optional[str] = None   # auto-detected for thereforeonline.com
    timeout: int = 60


def load_config_from_env() -> ThereforeConfig:
    """Load Therefore connection details from environment variables.

    Expected env vars:
        THEREFORE_URL       https://acme.thereforeonline.com/theservice/v0001
        THEREFORE_USERNAME  service_account
        THEREFORE_PASSWORD  secret
        THEREFORE_TENANT    acme  (optional — auto-detected for thereforeonline.com)
    """
    url = os.environ.get("THEREFORE_URL")
    if not url:
        raise EnvironmentError("THEREFORE_URL environment variable not set")

    return ThereforeConfig(
        server_url=url,
        username=os.environ["THEREFORE_USERNAME"],
        password=os.environ["THEREFORE_PASSWORD"],
        tenant=os.environ.get("THEREFORE_TENANT"),
        timeout=int(os.environ.get("THEREFORE_TIMEOUT", "60")),
    )


def build_client_from_env() -> "ThereforeClient":
    """Build a ThereforeClient from environment variables."""
    cfg = load_config_from_env()
    return ThereforeClient(cfg.server_url, cfg.username, cfg.password, cfg.tenant)


# Usage — recommended script pattern:
#
#   1. Create a .env file (never commit to source control):
#      THEREFORE_URL=https://acme.thereforeonline.com/theservice/v0001
#      THEREFORE_USERNAME=batch_user
#      THEREFORE_PASSWORD=s3cret
#
#   2. Load with python-dotenv (pip install python-dotenv):

try:
    from dotenv import load_dotenv
    load_dotenv()           # reads .env in current dir
except ImportError:
    pass                    # skip if not installed; rely on actual env vars

client = build_client_from_env()

if not client.test_connection():
    raise SystemExit("Cannot connect to Therefore server — check credentials")

print("Connected to Therefore")
```

---

## Multi-Category Query (ExecuteAsyncMultiQuery)

Query documents across multiple categories in a single API call.

```python
def search_multi_category(client, queries: list, row_block_size: int = 200) -> dict:
    """
    Query multiple Therefore categories simultaneously.

    Args:
        queries: list of query dicts, each with 'CategoryNo', 'Conditions', etc.
                 Each dict also needs a unique 'QueryId' key for identification.
    Returns:
        dict mapping each input QueryId to its list of result documents.
    """
    # Build request — each query needs its own RowBlockSize
    request_queries = []
    for q in queries:
        rq = dict(q)
        rq.setdefault("MaxRows", 0)
        rq.setdefault("RowBlockSize", row_block_size)
        rq.setdefault("Mode", 0)
        request_queries.append(rq)

    result = client.post("ExecuteAsyncMultiQuery", {"Queries": request_queries})

    # Result contains a list of QueryResults, one per input query
    all_results = {}
    query_results = result.get("QueryResults", [])

    for i, qr in enumerate(query_results):
        query_result = qr.get("QueryResult", {})
        columns = query_result.get("Columns", [])
        col_map = {j: col.get("ColName") or col.get("Caption")
                   for j, col in enumerate(columns)}

        docs = []
        for row in query_result.get("ResultRows", []):
            doc = {"DocNo": row["DocNo"]}
            for j, val in enumerate(row.get("IndexValues", [])):
                if j in col_map:
                    doc[col_map[j]] = val
            docs.append(doc)

        cat_no = request_queries[i].get("CategoryNo", i)
        all_results[cat_no] = docs

    return all_results


# Usage — query invoices and purchase orders simultaneously:
results = search_multi_category(client, queries=[
    {
        "CategoryNo": 8,
        "Conditions": [{"FieldNoOrName": "Status", "Condition": "Pending"}],
        "SelectedFieldsNoOrNames": ["Invoice_No", "Amount", "Status"],
    },
    {
        "CategoryNo": 12,
        "Conditions": [{"FieldNoOrName": "Status", "Condition": "Pending"}],
        "SelectedFieldsNoOrNames": ["PO_Number", "Supplier", "Status"],
    },
])

invoices = results.get(8, [])
purchase_orders = results.get(12, [])
print(f"Found {len(invoices)} pending invoices, {len(purchase_orders)} pending POs")
```

**Note:** `ExecuteAsyncMultiQuery` does not use the same `QueryId`/`GetNextSingleQueryRows`
pattern as single queries — results are returned inline. For large result sets across
multiple categories, prefer multiple `search_all()` calls.

---

## Workflow Task Management

Query, claim, and complete workflow tasks programmatically.

```python
def get_my_tasks(client) -> list:
    """Get workflow tasks assigned to the current user (ExecuteTaskInfoQuery)."""
    result = client.post("ExecuteTaskInfoQuery", {})
    return result.get("TaskInfos", [])


def get_all_workflow_tasks(client, process_no: int = None) -> list:
    """Get all workflow tasks, optionally filtered by process number."""
    payload = {}
    if process_no:
        payload["ProcessNo"] = process_no
    result = client.post("ExecuteTaskInfoQuery", payload)
    return result.get("TaskInfos", [])


def complete_task(client, task_no: int, exit_no: int = 1,
                  comment: str = "") -> bool:
    """Complete a workflow task with the specified exit/transition."""
    payload = {
        "TaskNo": task_no,
        "SelectedExitNo": exit_no,
    }
    if comment:
        payload["Comment"] = comment
    try:
        client.post("CompleteTask", payload)
        return True
    except Exception as e:
        print(f"Failed to complete task {task_no}: {e}")
        return False


def get_task_document(client, task_info: dict) -> dict:
    """Get the document linked to a workflow task."""
    doc_no = task_info.get("DocNo")
    if not doc_no:
        return {}
    return get_index_data(client, doc_no)


# Usage — process all approval tasks:
tasks = get_my_tasks(client)
print(f"Found {len(tasks)} workflow tasks")

for task in tasks:
    task_no    = task.get("TaskNo")
    task_name  = task.get("TaskName", "")
    doc_no     = task.get("DocNo")
    process    = task.get("ProcessName", "")

    print(f"  Task {task_no}: {task_name} | Process: {process} | DocNo: {doc_no}")

    # Get the document linked to this task
    if doc_no:
        index_data = get_task_document(client, task)
        invoice_no = get_field_value(index_data, "Invoice_No")
        amount     = get_field_value(index_data, "Amount")
        print(f"    Invoice: {invoice_no}, Amount: {amount}")

    # Complete the task (exit 1 = Approve, exit 2 = Reject — depends on workflow)
    # complete_task(client, task_no, exit_no=1, comment="Auto-approved by batch")

# Query all tasks for a specific workflow process:
ap_tasks = get_all_workflow_tasks(client, process_no=3)
print(f"AP workflow has {len(ap_tasks)} outstanding tasks")
```

**TaskInfo fields:**
| Field | Description |
|-------|-------------|
| `TaskNo` | Unique task identifier |
| `TaskName` | Display name of the task step |
| `ProcessName` | Name of the workflow process |
| `DocNo` | Document linked to this task (if any) |
| `AssignedTo` | Username of the assigned user |
| `CreatedDate` | When the task was created (WCF date string) |
| `DueDate` | Task due date (WCF date string, may be null) |

---

## Update Document (UpdateDocument2)

Updating index data requires fetching `LastChangeTime` from the current document first —
the server rejects updates without it as a concurrency safeguard.

```python
def update_document(client, doc_no: int, updated_items: List[Dict],
                    fill_dependent: bool = True,
                    comments: str = "") -> bool:
    """
    Update index fields on an existing document.

    Args:
        doc_no:          Therefore document number.
        updated_items:   List of typed index data items to update (only changed fields
                         needed — unchanged fields can be omitted).
        fill_dependent:  Re-evaluate calculated/dependent fields after update.
        comments:        Optional check-in comment.

    Returns:
        True on success; raises on HTTP error.

    Workflow:
        1. GET current document to obtain LastChangeTime (required for concurrency check).
        2. POST UpdateDocument2 with LastChangeTime + new IndexDataItems.
    """
    # Step 1: Fetch current document to get LastChangeTime
    current = client.post("GetDocumentIndexData", {"DocNo": doc_no})
    index_data = current.get("IndexData", {})
    last_change_time     = index_data.get("LastChangeTime")           # WCF format
    last_change_time_iso = index_data.get("LastChangeTimeISO8601")    # ISO 8601

    if not last_change_time and not last_change_time_iso:
        raise ValueError(f"Could not get LastChangeTime for DocNo {doc_no}")

    # Step 2: Update
    payload = {
        "DocNo": doc_no,
        "CheckInComments": comments,
        "IndexData": {
            "IndexDataItems": updated_items,
            "DoFillDependentFields": fill_dependent,
            "LastChangeTime": last_change_time,
            "LastChangeTimeISO8601": last_change_time_iso,
        }
    }
    client.post("UpdateDocument2", payload)
    return True


def update_field(client, doc_no: int, field_no: int, new_value,
                 field_type: str = "String") -> bool:
    """Convenience wrapper: update a single field by FieldNo."""
    type_map = {
        "String":   "StringIndexData",
        "Money":    "MoneyIndexData",
        "Int":      "IntIndexData",
        "Date":     "DateIndexData",
        "DateTime": "DateTimeIndexData",
        "Logical":  "LogicalIndexData",
    }
    type_key = type_map.get(field_type, "StringIndexData")
    item = {type_key: {"FieldNo": field_no, "DataValue": new_value}}
    return update_document(client, doc_no, [item])


# Usage:
# Update invoice status and add a comment
status_kw_no = resolve_keyword(client, category_no=8, field_no=105, display_name="Approved")

update_document(client, doc_no=265461,
    updated_items=[
        keyword_field(105, status_kw_no),
        str_field(110, "Approved by batch process"),
    ],
    comments="Auto-approved via AP batch run"
)

# Quick single-field update:
update_field(client, doc_no=265461, field_no=103, new_value=1850.00, field_type="Money")
```

---

## Multi-Keyword Field Builder

For fields that accept multiple keyword values (`MultipleKeywordData`).

```python
def multi_keyword_field(field_no: int, keyword_nos: List[int]) -> dict:
    """Multiple-keyword field — list of KeywordNo values."""
    return {
        "MultipleKeywordData": {
            "FieldNo": field_no,
            "Keywords": [{"KeywordNo": kno} for kno in keyword_nos]
        }
    }


def resolve_keywords(client, category_no: int, field_no: int,
                     display_names: List[str]) -> List[int]:
    """Resolve multiple keyword display names to KeywordNo values."""
    result = client.post("GetKeywordsByFieldNo", {
        "FieldNo": field_no,
        "CategoryNo": category_no,
        "ShowDeactivatedKeywords": False
    })
    kw_map = {kw["KeywordName"].lower(): kw["KeywordNo"]
              for kw in result.get("Keywords", [])}
    resolved = []
    for name in display_names:
        kno = kw_map.get(name.lower())
        if kno is None:
            raise ValueError(f"Keyword '{name}' not found for field {field_no}")
        resolved.append(kno)
    return resolved


# Usage — tag a document with multiple cost centres:
cost_centre_nos = resolve_keywords(client, category_no=8, field_no=108,
                                   display_names=["IT", "Finance"])

index_items = [
    str_field(101, "INV-2024-099"),
    multi_keyword_field(108, cost_centre_nos),
]
```

---

## Full-Text Search (ExecuteFullTextQuery)

Search document content (not just index fields) using full-text keywords.

```python
def full_text_search(client, search_text: str,
                     category_no: int = None,
                     max_rows: int = 100) -> List[Dict]:
    """
    Search document content using full-text indexing.

    Unlike ExecuteSingleQuery (which searches index fields), this searches
    the actual file content — useful for finding PDFs or Word docs
    containing specific phrases.

    Args:
        search_text:  Words or phrase to search for.
        category_no:  Optional — restrict to one category.
        max_rows:     Maximum results to return (default 100).
    """
    payload = {
        "FullTextQuery": {
            "SearchText": search_text,
            "MaxRows": max_rows,
        }
    }
    if category_no:
        payload["FullTextQuery"]["CategoryNo"] = category_no

    result = client.post("ExecuteFullTextQuery", payload)
    query_result = result.get("QueryResult", {})

    columns = query_result.get("Columns", [])
    col_map = {i: col.get("ColName") or col.get("Caption")
               for i, col in enumerate(columns)}

    documents = []
    for row in query_result.get("ResultRows", []):
        doc = {"DocNo": row["DocNo"]}
        for i, val in enumerate(row.get("IndexValues", [])):
            if i in col_map:
                doc[col_map[i]] = val
        documents.append(doc)

    return documents


# Usage:
# Find all documents mentioning an invoice number anywhere in the file content:
docs = full_text_search(client, search_text="INV-2024-001", category_no=8)
print(f"Found {len(docs)} documents containing 'INV-2024-001'")

# Phrase search — quote the phrase:
docs = full_text_search(client, search_text='"purchase order" "approved"')

# Broad search across all categories:
docs = full_text_search(client, search_text="urgent review required", max_rows=50)
```

**Notes:**
- Full-text search requires the Therefore full-text index to be enabled and up to date.
- Returns results synchronously (no `QueryId` pagination — use `MaxRows` to limit).
- Index field values are included in results alongside document numbers.
