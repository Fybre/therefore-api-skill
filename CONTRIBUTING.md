# Contributing

When changing an API contract:

1. Update `references/operation_contracts.json` with the method and required members.
2. Add or update a redacted request/response fixture and payload test.
3. Update every affected example in `SKILL.md` and `references/`.
4. Record the Therefore Web API/server version, auth mode, verification date, and whether the
   call was read-only or used a disposable object.
5. Run the compile and unit-test commands from `README.md`.

Never commit credentials, tenant-specific personal data, document contents, tokens, or raw
error payloads containing secrets. Mutation tests must use explicitly disposable objects and
clean them up only when the test created them.

Use `AUDIT.md` for remaining coverage work. A finding should be marked resolved only when the
documentation, client payload, and regression test agree.
