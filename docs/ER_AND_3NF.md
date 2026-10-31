# Current PostgreSQL ER model and 3NF justification

This document describes application schema, the served collaboration workspace. Exact columns, keys, indexes and constraints are in `schema_postgresql.sql`; the source model is `research/database/models.py`.

## Relations

| Entity / relationship | Key and role |
|---|---|
| source_record | id; unique source_key; URL, capture time, content hash and evidence payload |
| school | id; unique code; Vellore campus constraint |
| department | id; unique(school_id, code) and(school_id, name); school FK |
| faculty | id; unique source_key and canonical_url; department and source FKs |
| faculty_qualification | id; unique source_key; faculty and source FKs |
| faculty_external_profile | id; unique(faculty_id, provider, external_id); verification state and evidence |
| research_area | id; unique normalized_term; display name |
| faculty_research_area | (faculty_id, area_id); source and assignment method |
| venue | id; unique source_key; publication-venue metadata |
| publication | id; unique source_key and nullable DOI; venue and source FKs |
| faculty_publication | (faculty_id, publication_id); original order, corresponding status, verified source |
| publication_research_area | (publication_id, area_id); sourced assignment |
| lab | id; unique source_key; school, official source, description/contact |
| faculty_lab | (faculty_id, lab_id); sourced membership role |
| lab_research_area | (lab_id, area_id); sourced assignment |
| project | id; unique source_key; source-listed project observation and status |
| faculty_project | (faculty_id, project_id); sourced participant role, nullable if unknown |
| project_research_area | (project_id, area_id); sourced assignment |
| faculty_metric_snapshot | id; unique(faculty_id, provider, source_id); dated provider values |
| patent | id; unique source_key; source status observation, not canonical invention |
| patent_inventor | (faculty_id, patent_id); nature and source of inventor evidence |
| user_account | id; unique username and nullable faculty_id; password hash and application role |
| publication_audit | id; operation, time, publication identifier and immutable old/new row evidence |

Main cardinalities: school 1:Ndepartment;department 1:Nfaculty;faculty 1:Nqualification and externalprofile;facultyM:Nresearcharea/publication/lab/project/patent;lab/project/publicationM:Nresearcharea;venue 1:Npublication;faculty 1:Nmetric snapshots;faculty 0:1 account. Sources support many assertions. The audit deliberately retains a publication identifier without a deletion-blocking FK so deletion history survives.

## Functional dependencies and normalization

- School identity determines its name/campus. Department identity determines its school and name; school names are not repeated on faculty.
- Faculty identity determines official professional fields and its department. Qualifications and external identities are separate repeating relations; publication lists are not stored in faculty text fields.
- Publication identity determines title, year, type, venue and source assertion. Venue attributes depend on venue identity and live in venue. Nullable DOI is an alternate exact identity when present.
- The full authorship key(faculty, publication) determines order/corresponding state and evidence. A faculty alone or paper alone does not determine those relationship attributes. The same reasoning applies to lab/project membership junctions.
- A normalized research term determines its display record; each owner–area pair determines source and assignment method. Shared interests are derived joins rather than duplicated collaborator lists.
- A metric observation depends on faculty, provider and captured source. It does not functionally depend on faculty alone; providers and dates may disagree. No latest metric is redundantly copied into faculty.
- Project and patent rows represent **source observations**. Their source key determines the observed fields. Identical titles do not establish canonical project/invention identity. Future canonicalization must preserve these observation records.
- User credentials and application roles belong to account identity. They are not academic qualifications or patent-inventor relationships.

These operational relations have atomic fields, no repeating multi-value relationship columns, no attributes dependent on only part of a composite key, and no school/department/venue transitive duplication. They therefore follow 3NF at their declared grain. Source payloads and audit JSONB are intentional immutable evidence documents, not substitutes for relational membership/authorship. Raw authors preserve unmatched provider names; normalized verified faculty relationships are in faculty_publication.

## Derived structures and integrity

Four views derive coauthor pairs, shared-area pairs, faculty discovery and facility discovery. Aggregates are computed separately before joining to avoid multiplication of counts. Publication counts remainNULL until collection is completed or partial. The distance function and two-hop query operate on authorship, not stored guessed edges. Unknown lab membership remains absent.

Foreign keys reject orphan relationships; unique constraints prevent duplicate normalized identities and memberships; CHECK constraints reject unverified authorship, invalid roles, negative metrics and unsupported campuses/schools. A partial unique index prevents one verified external identity being assigned to two faculty. Reverse junction indexes support area and publication lookups. A publication audit trigger records actual row changes.
