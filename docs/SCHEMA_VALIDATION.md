# PostgreSQL schema validation

Recorded validation used PostgreSQL 16 in Docker on 20 October 2026, before the
submission's filenames and database target were renamed. The current package uses
`vit_research_app`; the renamed configuration has not been rerun against PostgreSQL.
The original database was preserved during the recorded validation.

## Directory migration

The closed `data/staging/batch_001_directory` batch loaded transactionally and
was loaded a second time with identical entity/relationship counts. No employee
ID was inferred from the canonical profile URL.

| Relation | Directory batch rows |
|---|---:|
| School | 2 |
| Department | 10 |
| Selected faculty | 337 |
| Faculty qualification | 954 |
| External profile claim | 1,021 |
| Research area | 451 |
| Faculty–area relation | 1,315 |
| Profile-listed project observation | 223 |
| Faculty–project relation | 223 |
| Patent-status observation | 389 |
| Faculty–patent relation | 389 |
| VIT-reported metric snapshot | 274 |

Faculty coverage is SCOPE 222 and SCORE 115. These are selected extractable
profiles, not a complete staff headcount. Directory-only import supplies no
publication records or verified lab membership. Publication collection remains
`NOT_ATTEMPTED` until a separate verified enrichment batch is imported.

Project observations remain keyed to the official faculty listing. Similar titles
across profiles are not claimed to be distinct real-world projects or silently
merged. An official page's undated “ongoing” label is stored as a source-reported
status with unknown status-as-of. Patent rows are status observations, not unique
inventions. Book/other contribution tables remain source evidence until their
publication identity and authorship are resolved.

## Automated checks

Command from the project root:

```sh
docker compose --profile test run --rm --no-deps \
  -v /Users/ramsidharthachebrolu/Desktop/vit-research-intelligence:/work:ro \
  -w /work tests python -m pytest -q tests/test_schema.py \
  -W error -o cache_dir=/tmp/pytest-research
```

Result: **8 passed in 14.57 seconds**. Each test used a random isolated schema in
`vit_research_test`; its schema was removed afterward. These tests verify:

- Fresh initialization and submitted SQL DDL both produce 23 tables and four views.
- Directory reload preserves enrichment state and verified external claims.
- Shared areas require explicit source-declared or manually reviewed links.
- Direct coauthors count distinct papers; two-hop introductions return actual
  intermediate faculty and one deterministic paper witness per edge, excluding
  self and direct collaborators.
- Stored distance returns 0, 1, 2 or NULL within the declared depth bound.
- Unretrieved publications render NULL; a completed retrieval with no loaded
  papers may legitimately return zero.
- Unverified authorships and duplicate author order fail database constraints;
  gaps in original author order are retained.
- A verified external identity cannot belong to two faculty.
- Publication INSERT/UPDATE/DELETE events retain old/new source rows through the
  audit trigger.
- Verified enrichment retains provider-labelled h-index/i10/citations, normalized
  DOI, original author position and evidence; unchanged reload creates no extra
  publication audit event.
- Foreign schemas are refused rather than overwritten.

All 15 statements in `docs/SQL_SHOWCASE.sql` also executed successfully against
the initial directory database. Publication examples return no rows before
provider enrichment; they are not populated with invented records.

## Import interface

`research.database.sql.initialize_schema(engine)` accepts an empty or compatible
application schema. `loader.load_directory(connection, folder)` and
`loader.load_enrichment(connection, folder)` run inside the caller's transaction.
The standalone command guards targets to PostgreSQL databases ending in `_app` or
`_test`:

```sh
python scripts/load_directory.py --initialize \
  --batch data/staging/batch_001_directory \
  --enrichment data/staging/BATCH_NAME --report /tmp/load-report.json
```

Set `DATABASE_URL` securely before running; no credentials belong in the command
or report. Omit `--enrichment` when loading only the directory. Enrichment is an
independent closed checksum-validated `enrichment.json` batch. Its authorships
must reference matched provider identities and carry `VERIFIED` status. Provider
responses are retained as source records. Metrics from the VIT page and OpenAlex
stay separate rather than being blended.

## Final publication import

The frozen final provider batch is
`data/staging/batch_005_verified_publications`, referenced by
`data/staging/LATEST_ENRICHMENT`. Only this batch belongs in a fresh submission
build. Earlier enrichment batches are historical iterations, not additive inputs.

Final005 imported successfully and its repeated import preserved every table
count, including publication audit history (21.3 seconds combined). It contains
194 independently matched faculty, 4,391 loaded publications, 4,740 verified
internal authorships, 1,087 venues and 129 distinct coauthor pairs. All 194 matched
faculty have publication records and status `RETRIEVED`. The other directory
candidates remain internal: 59 need identity review and 84 lack a successful
cached response. The public predicate is retrieval status plus at least one
verified authorship, giving **194 public profiles: SCOPE 130 and SCORE 64**.

| School | Department | Public faculty with records |
|---|---|---:|
| SCOPE | Analytics | 21 |
| SCOPE | Computational Intelligence | 29 |
| SCOPE | Database Systems | 25 |
| SCOPE | Information Security | 18 |
| SCOPE | IoT | 18 |
| SCOPE | Quantum AI | 1 |
| SCOPE | Software Systems | 18 |
| SCORE | Computer Applications | 19 |
| SCORE | Information Technology | 17 |
| SCORE | Software & Systems Engineering | 28 |

All 15 SQL showcase statements executed successfully again after final publication
loading. A real-data check starting at Dr. Sweta Bhattacharya (canonical profile
13096, database faculty ID 221 in this database) returned 23 two-hop path
witnesses. For example, Dr. Debi Prasanna Acharjya is reached through Dr. Chiranji
Lal Chowdhary, backed by publication IDs 4303 and 1788. The stored function
independently returned distance 2. Database IDs are installation-specific; the
canonical profile source key is the portable identifier.

The integration database briefly loaded corrected batch004 before frozen005.
These two have identical verified faculty identities, and005 is a strict work
superset. Its source/audit tables therefore preserve a few historical observations
beyond a fresh005-only install. This is retained provenance, not duplicated works
or authorships. Earlier unsafe batches002/003 were never imported;003 was refused
by the duplicate-authorship validator before mutation.
