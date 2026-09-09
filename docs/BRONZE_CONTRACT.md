# Bronze Storage Contract

## Purpose and grain

Bronze preserves source-oriented provider history for replay, lineage, and debugging. One successful provider response is one immutable Bronze object. Pagination responses are stored independently and are never merged before persistence.

Each complete object is a pair:

```text
<bronze_id>.<json|csv>
<bronze_id>.meta.json
```

The first file contains the exact provider response bytes. The second is an application-generated metadata sidecar using schema version `1`.

## Layout and identity

Objects are partitioned by safe provider key, safe resource key, and the UTC fetch date:

```text
data/bronze/<provider>/<resource>/YYYY-MM-DD/
```

Provider and resource keys must match `^[a-z0-9][a-z0-9_]*$`. The Bronze ID combines a UTC timestamp with microsecond precision and a random hexadecimal suffix:

```text
YYYYMMDDTHHMMSSffffffZ_<random suffix>
```

For example:

```text
data/bronze/football_data_org/matches/2026-09-09/
├── 20260909T052030123456Z_a1b2c3d4e5f6.json
└── 20260909T052030123456Z_a1b2c3d4e5f6.meta.json
```

Only JSON and CSV payload formats are supported. The format selects the extension; content type does not. Payloads are accepted as bytes and are never parsed, decoded, normalized, or re-serialized before storage. This preserves whitespace, key order, encoding, delimiters, and line endings exactly.

## Metadata schema version 1

Each sidecar contains:

```json
{
  "schema_version": 1,
  "bronze_id": "20260909T052030123456Z_a1b2c3d4e5f6",
  "provider": "football_data_org",
  "resource": "matches",
  "fetched_at": "2026-09-09T05:20:30.123456Z",
  "ingest_date": "2026-09-09",
  "payload_file": "20260909T052030123456Z_a1b2c3d4e5f6.json",
  "payload_format": "json",
  "http_status": 200,
  "content_type": "application/json",
  "request": {
    "method": "GET",
    "endpoint": "/v4/competitions/PL/matches",
    "params": {"season": 2026}
  },
  "byte_size": 12345,
  "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

`byte_size` is the length of the exact raw payload, and `sha256` is computed from those same bytes. Request parameters must be sanitized and JSON-serializable before they reach the writer. Callers must never pass authorization headers, API tokens, cookies, passwords, secret-bearing URLs, or unsanitized request objects.

Only HTTP 2xx responses enter Bronze. M4 does not make HTTP requests or define an error-response capture policy.

## Immutability, duplicates, and completion

Bronze never deduplicates. Two byte-identical responses are two observations with distinct Bronze IDs and sidecars, while their checksums and byte sizes may match. Technical duplicate or unchanged-response handling belongs to staging; canonical and domain reconciliation belongs to Silver.

Writes use same-directory temporary files. The payload is committed first and the metadata sidecar last. The sidecar is the completion marker: readers must consider an object complete only when both files exist and the sidecar references the matching payload. Caught write failures clean temporary files and remove a newly committed payload if the sidecar cannot be committed. A hard process or operating-system crash may leave an orphan payload; without its sidecar, that payload is incomplete.

Committed payloads and sidecars are never updated, appended to, or intentionally overwritten. Every successful response creates a new observation.
