# Therefore API skill

Codex/Claude skill guidance and tested reference code for Therefore's `/restun` API.

The repository focuses on the API conventions that are easy to get wrong: Therefore Online
tenant headers, typed index data, query conditions, async pagination, document streams,
comments, cases, workflows, and full-text search.

## Contents

- `SKILL.md` — concise operational guidance loaded by an agent.
- `references/api_endpoints.md` — request/response reference.
- `references/python_examples.md` — raw REST and helper examples.
- `references/therefore_client.py` — focused standard-library reference client.
- `references/operation_contracts.json` — machine-readable contracts used by tests.
- `references/live_validation.md` — redacted, server-versioned live verification results.
- `references/powershell_reference.md` — PowerShell-specific patterns.
- `scripts/example.py` — read-only connection and metadata smoke test.
- `AUDIT.md` — function coverage, resolved findings, and remaining live-verification work.

## Validate locally

```bash
python3 -m compileall -q references scripts tests
python3 -m unittest discover -s tests -v
```

## Read-only smoke test

Set `THEREFORE_BASE_URL`, `THEREFORE_AUTH_METHOD`, `THEREFORE_USERNAME`,
`THEREFORE_PASSWORD`, and optionally `THEREFORE_TENANTNAME` in the environment or a local
`.env` file, then run:

```bash
python3 scripts/example.py --env-file .env
python3 scripts/example.py --env-file .env --category 8
```

The smoke script only authenticates and reads the accessible category tree/category metadata.
It does not create, update, or delete Therefore objects.

## Compatibility and verification

Live observations in the references are date-stamped. Contract fixtures record the upstream
catalogue commit used for verification. Behaviour can vary with Therefore server version and
configuration; state-changing operations should be verified in disposable categories,
workflows, dictionaries, and users before production use.

No licence has been selected yet. The repository owner must choose one before third-party
redistribution terms can be assumed.
