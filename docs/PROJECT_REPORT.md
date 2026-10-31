# VIT Research Connections

## Objective

We developed a DBMS application to help users discover potential research collaborators among selected faculty from SCOPE and SCORE at VIT Vellore. The application connects faculty profiles, research interests and publication records so users can inspect why a researcher appears in the results.

## Features

- Faculty directory with school, department and research-interest search.
- Collaborator suggestions based on shared declared interests, literal publication-title keywords, direct coauthorship and two-hop coauthor connections.
- Paper evidence for shared publications and introductions through a mutual coauthor.
- Faculty profiles with qualifications, collected papers, source-labelled metrics, reported projects and patent observations.
- Officially sourced facilities and outbound contact/profile links.
- Classroom accounts that link to a faculty profile as the starting point for searches.

## Technology and structure

The application uses Python, Flask, SQLAlchemy and PostgreSQL 16. Pages use server-rendered HTML templates and CSS. Docker Compose provides the application and database services.

`research/app.py` contains the routes and discovery workflow. `research/database/` defines the tables, loaders, views, function and audit trigger. Templates are in `research/templates/`. The `scripts/` directory contains startup, import, collection and packaging utilities. Included snapshots under `data/staging/` support operation without live research API requests.

## Database design

The database `vit_research_app` contains 23 tables. Core entities include school, department, faculty, research area, publication, venue, facility, project, patent, account and source record. Separate tables store qualifications, external identity claims, metric snapshots and publication audit entries.

Junction tables represent many-to-many relationships such as faculty–publication and faculty–research-area. Primary keys identify records; foreign keys maintain references; unique and check constraints prevent invalid or repeated relationships. Source records retain URLs, retrieval times and evidence payloads.

The project demonstrates:

- Four views for faculty discovery, coauthor pairs, shared research areas and facility discovery.
- Joins, self-joins, grouping, HAVING, CTEs and window functions in fifteen SQL examples.
- A bounded `fn_coauthor_distance` function for direct and two-hop connections.
- A publication audit trigger recording inserts, updates and deletes.
- Transactional imports and indexes on identifiers and relationship lookups.

The ER relationships and normalization are explained in `ER_AND_3NF.md`. The standalone schema and sample queries are in `schema_postgresql.sql` and `SQL_SHOWCASE.sql`.

## Data collection

Official VIT department and faculty pages provide roster evidence, qualifications, declared interests, institutional contact information and profile-reported contributions. OpenAlex provides publication metadata and author metric snapshots. Author profiles are matched using official ORCID links, compatible names and VIT affiliation evidence; official directory sources establish Vellore school membership.

The snapshot includes 337 directory candidates. The faculty directory and collaborator workflow select 194 with matched author profiles and collected papers: 130 from SCOPE and 64 from SCORE. The collection includes 4,391 papers since 2019, 4,740 faculty–paper links and 129 internal coauthor pairs.

The database also holds 12 sourced facilities, 223 project observations and 389 patent-status observations. Project observations come from the broader directory collection, including faculty outside the 194-person publication subset. Repeated project or patent entries are not counts of distinct projects or inventions.

Collection methods and provider limitations are documented in `PUBLICATION_EXTRACTION.md`.

## Matching logic

Shared interests use exact normalized research-area terms. Keyword searches use literal, case-insensitive matching against publication titles. When a keyword is entered, only faculty with a collected paper title matching that keyword are included in the results. A direct connection means that both matched author profiles appear on a collected paper. A two-hop introduction identifies a mutual coauthor and a paper supporting each link; self and direct coauthors are excluded from those introductions.

For a selected researcher, results are ordered by shared-area count, connection distance and name. Metrics do not determine the matches. The application uses no ML or semantic similarity.

## Limitations

This is a selected collection, not a complete or continuously updated university research database. Author-profile matching does not manually verify each paper, and provider metadata can contain errors. The freshness of individual official faculty pages has not been established.

A missing direct or two-hop path means that no such path was found in the collected records. Research interests do not establish collaboration or lab membership. Provider career metrics are separate from the papers loaded here, and retrieval dates are not necessarily metric calculation dates. Missing values remain unknown rather than becoming zero.

Accounts and roles are illustrative classroom features; linking a faculty profile does not prove ownership. Journal impact factors and scholar/student rosters are outside the project scope.

## Tests and execution

The submission includes 18 tests: 12 PostgreSQL schema/route checks and six offline collector checks. The six offline checks passed. The PostgreSQL tests and Docker build have not been rerun for the current package; recorded earlier results are in `TEST_REPORT.md`.

The README contains startup and test commands.
