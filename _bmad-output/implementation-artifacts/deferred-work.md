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
- source_spec: none
  summary: Platform MCP as extensible tool registry, role-gated (agent-platform-plan Phase 8)
  evidence: Split from agent-platform intent — depends on the invocation pipeline and agent roles, deferred independently
- source_spec: none
  summary: Cost & usage monitoring dashboard (agent-platform-plan Phase 9)
  evidence: Split from agent-platform intent — usage rows land during invocation, dashboard deferred independently
- source_spec: none
  summary: Scheduled invocation of agents (agent-platform-plan Phase 10)
  evidence: Split from agent-platform intent — builds on the invocation pipeline, deferred independently
- source_spec: none
  summary: Extension guide ("add a tasks entity") + hardening notes (agent-platform-plan Phase 11)
  evidence: Split from agent-platform intent — documentation phase, deferred until the pipeline exists
