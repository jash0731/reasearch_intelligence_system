# VIT Research Connections

A DBMS project for discovering potential research collaborators among selected **SCOPE and SCORE faculty at VIT Vellore**. Users can explore faculty profiles, search publication titles and inspect shared interests or coauthor connections before following an official contact link.

## Features

- Faculty directory with name, department, research-interest and school filters.
- Collaborator suggestions through shared declared interests, common papers and mutual coauthors.
- Literal publication-title keyword search, with supporting papers in the results.
- Faculty profiles with qualifications, collected publications, provider-labelled metrics and reported projects/patents.
- Officially sourced labs and facilities.
- Demo accounts with a linked faculty profile as the starting point for discovery.

Matching uses relational joins and literal keywords. The project uses no ML or semantic similarity.

## Technology

| Component | Technology |
|---|---|
| Application | Python and Flask |
| Database | PostgreSQL 16, database `vit_research_app` |
| Database access | SQLAlchemy |
| Frontend | Server-rendered HTML and CSS |
| Local deployment | Docker Compose and Waitress |

## GitHub repository

Source repository: [jash0731/reasearch_intelligence_system](https://github.com/jash0731/reasearch_intelligence_system).

## Run locally

Install Docker Desktop with Docker Compose and Python 3. Start Docker Desktop, extract the ZIP and open a terminal in the folder containing `compose.yaml`.

Generate local configuration:

```sh
python3 scripts/configure.py
```

On Windows, use `python` instead of `python3` if that is your Python command.

Build and start the application:

```sh
docker compose up --build -d --wait
```

Open **http://127.0.0.1:5050**. The first build downloads container images and Python dependencies. Startup creates the schema, imports the included snapshots and creates demo accounts. It does not call external research APIs.

Public browsing requires no login. The demo usernames are `admin`, `hod`, `faculty_senior` and `faculty_early`. Their initial password is the generated `DEMO_PASSWORD` value in the local `.env` file. Accounts and role labels are classroom examples; linking a profile does not verify ownership.

Configuration also generates application and database secrets in `.env`. Keep that file private. If port 5050 is occupied, change `COMPOSE_APP_PORT` in `.env` and run the startup command again.

Stop the services:

```sh
docker compose stop
```

Start them again:

```sh
docker compose up -d --wait
```

Database storage persists between starts. Application startup reloads the included snapshots. To inspect a startup problem, use `docker compose logs app db`.

## Included data

| Collection | Count |
|---|---:|
| Faculty in the directory and collaborator workflow | 194 |
| SCOPE / SCORE | 130 / 64 |
| Collected papers since 2019 | 4,391 |
| Faculty–paper links | 4,740 |
| Internal coauthor pairs | 129 |
| Sourced facilities | 12 |

The source directory snapshot contains 337 candidates. Projects and patents are observations from that broader collection, including faculty outside the 194-person publication subset. Repeated observations are not distinct-project or distinct-invention counts.

The application loads `data/staging/batch_001_directory`, the enrichment batch named by `LATEST_ENRICHMENT`, and `labs.json`. The included enrichment batch is `batch_005_verified_publications`. Collection scripts are optional tools; normal startup uses the included data rather than recollecting it.

## Database concepts

The schema contains **23 tables**, with primary keys, foreign keys, uniqueness and check constraints. Junction tables represent many-to-many relationships such as faculty–publication and faculty–research-area.

The submission includes four views, fifteen SQL examples using joins, aggregation, CTEs and window functions, a bounded coauthor-distance function, and a publication audit trigger that records old/new row data.

After starting the services, run the SQL examples:

```sh
docker compose cp docs/SQL_SHOWCASE.sql db:/tmp/SQL_SHOWCASE.sql
docker compose exec -T db psql -U vit_app -d vit_research_app -v ON_ERROR_STOP=1 -f /tmp/SQL_SHOWCASE.sql
```

## Project structure

```text
research/
  app.py                  Routes, accounts and discovery queries
  facilities_loader.py       Facility import
  database/                 Models, data loaders, views, function and trigger
  templates/              HTML pages
  static/style.css              Styles
scripts/                     Configuration, startup, collection and packaging
data/staging/             Included offline data snapshots
tests/                       Schema, route and collector checks
docs/                        Project report, database design and SQL examples
compose.yaml                 Application and PostgreSQL services
Dockerfile                   Application and test images
run.py                       Server entry point for a prepared environment
```

## Tests

With the database service running:

```sh
docker compose --profile test build tests
docker compose --profile test run --rm tests
```

The suite contains 18 tests: 12 PostgreSQL schema/route checks and six offline collector checks. Database tests use temporary schemas in `vit_research_test`. For an independently managed test server, set `TEST_DATABASE_URL` to a dedicated PostgreSQL database whose name ends in `_test`.

The six offline tests passed. The PostgreSQL tests and Docker build have not been rerun for the current package. Recorded earlier verification is in [TEST_REPORT.md](docs/TEST_REPORT.md).

## Limitations

The collection is selected and may be incomplete. OpenAlex author profiles are matched using ORCID, compatible names and VIT affiliation evidence; this does not manually verify every individual publication. Official faculty-page freshness has not been established.

A missing coauthor path means no direct or two-hop connection was found in the collected records. Shared interests do not prove collaboration or lab membership. Provider career metrics are separate from collected-paper counts, and retrieval dates are not necessarily metric calculation dates. Unknown values are presented as unavailable.

## Documentation

- [Project report](docs/PROJECT_REPORT.md)
- [ER relationships and normalization](docs/ER_AND_3NF.md)
- [Publication collection method](docs/PUBLICATION_EXTRACTION.md)
- [PostgreSQL schema](docs/schema_postgresql.sql)
- [SQL examples](docs/SQL_SHOWCASE.sql)
- [Schema validation evidence](docs/SCHEMA_VALIDATION.md)

`python3 scripts/package_submission.py` creates the submission ZIP from the project files and approved snapshots. Local secrets and raw response caches are excluded.

## Viva / faculty demonstration

1. Open `scripts/extract_directory.py` and `scripts/enrich_directory.py` to explain VIT directory extraction and OpenAlex enrichment.
2. Inspect `data/staging/batch_001_directory/faculty_directory.json` and `data/staging/batch_005_verified_publications/enrichment.json` for actual extracted records.
3. Show the two `quality_report.json` files and `docs/PUBLICATION_EXTRACTION.md` to discuss author matching and held records.
4. Run `python -m pytest tests/test_author_identity.py -q` after installing the test dependencies; the six collector checks do not require the running PostgreSQL service.
5. Open `docs/schema_postgresql.sql` to demonstrate primary keys, foreign keys and uniqueness constraints.
6. Explain the incomplete faculty coverage, external-provider uncertainty and limited coauthor graph scope.

**Security:** Do not commit `.env`, passwords, API credentials, database dumps or local virtual environments. The included `.gitignore` excludes common local secrets and generated files.
