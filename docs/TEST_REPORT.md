# Recorded verification before submission cleanup — 20 October 2026

Before cleanup, the combined application suite passed **83 tests in 42.47 seconds** on PostgreSQL 16 through Docker:

```sh
docker compose --profile test build app tests
docker compose --profile test run --rm tests python -m pytest -q -W error -o cache_dir=/tmp/pytest-research
```

That recorded suite contained 65 earlier-implementation regression checks, 8 schema/loader checks, 4 route checks and 6 offline collector checks. The cleaned submission retains the 18 checks. The 83-pass result is historical evidence and does not represent a post-cleanup run. The README records the checks performed after cleanup. Tests create isolated random schemas inside `vit_research_test` and remove them afterward. Production demo tables are not test fixtures.

## Verified behavior

- Standalone submitted DDL and the Python model create the same 23 tables and 4 views.
- Directory and final publication imports are transactional and repeatable. Unchanged publication reimport does not create audit noise.
- Verified external identities cannot be attached to two faculty. Unverified authorship, duplicate original order and orphan references are rejected.
- Direct coauthors count distinct shared papers. Two-hop introductions exclude self/direct neighbors and contain real intermediate people and both paper witnesses.
- The PostgreSQL function returns 0, 1, 2 orNULL within its bounded scope. Missing/unretrieved publication counts remainNULL; a genuinely completed zero-result retrieval may return 0.
- Publication INSERT/UPDATE/DELETE triggers retain old/new row evidence, including after deletion.
- Exact-area matching excludes inferred interests. Literal keyword input does not treat `%` as a wildcard. Directory filters and evidence-rich page rendering pass.
- CSRF is required on account POST requests. Login uses a linked profile and refuses external redirect targets. Signup links an existing profile without creating an invented faculty row.
- Offline collector tests cover name/initial compatibility, name conflicts, required VIT affiliation, pagination beyond 100, restricted-cursor fallback and duplicated provider authors.

## Live integration

The recorded Docker runtime/test builds and health checks passed before the submission's filenames and database target were renamed. The current application factory is `research.app.create_app`, and the current package targets `vit_research_app`. The renamed configuration has not been rerun against PostgreSQL.

Final snapshot:337 internaldirectory candidates;194 public faculty (130 SCOPE, 64 SCORE);4,391 publications;4,740 authorship links;129 coauthor pairs;12 officialfacility records. All 194 accepted authors completed provider pagination. All 15 showcase SQL statements execute on the populated application database. A real distance 2 example connects Sweta Bhattacharya to Debi Prasanna Acharjya through Chiranji Lal Chowdhary with two recorded publications.

HTTP smoke checks cover health, collaborator suggestions, faculty detail/directory, publications, labs, projects, coverage andlogin. Browser inspection of real collaborator and publication records confirms the new content is rendered without the graph. A browser controller changed tabs during inspection, so browser checks are limited to observed screens; no broad accessibility certification is claimed.

## Practical limits

143 external identity candidates remain held. Provider and official-page metadata can be incomplete or mistaken despite checks. Lab memberships are undocumented. Project/patent rows are source observations. Identity ownership verification, production SSO and journal impact factors are outside scope. The archived monthly announcement data is not imported into publication authorship.

Additional detailed evidence: `SCHEMA_VALIDATION.md` and `PUBLICATION_EXTRACTION.md`. Historical reports about SQLite, 65 tests and graph PNG export describe the preserved v1 implementation, not the served workspace.
