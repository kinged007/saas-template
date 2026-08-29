- source_spec: `_bmad-output/implementation-artifacts/spec-extendable-user-profiles.md`
  summary: Regenerate .codesight wiki in CI rather than committing manual edits
  evidence: Blind hunter found .codesight/*.md staged as manual edits though they are auto-generated via npx codesight --wiki
- source_spec: `_bmad-output/implementation-artifacts/spec-extendable-user-profiles.md`
  summary: Add *.db to .gitignore to avoid committing test_saas_template.db artifacts
  evidence: Diff shows apps/api/test_saas_template.db modified and apps/api/test_alembic.db untracked
- source_spec: `_bmad-output/implementation-artifacts/spec-extendable-user-profiles.md`
  summary: Add frontend unit test harness for getProfileField precedence
  evidence: Verification gap found no tests for apps/web/src/types.ts getProfileField — repo has zero web *.test.* files and no test script
- source_spec: `_bmad-output/implementation-artifacts/spec-extendable-user-profiles.md`
  summary: Add alembic migration backfill integration test for 0006
  evidence: Existing tests use Base.metadata.create_all not alembic command.upgrade, so INSERT SELECT backfill idempotency is unverified
- source_spec: `_bmad-output/implementation-artifacts/spec-extendable-user-profiles.md`
  summary: Consider POST alternative for DELETE /me confirm to handle proxy stripping
  evidence: Edge case notes DELETE bodies may be stripped by proxies; current spec uses DELETE with JSON body
