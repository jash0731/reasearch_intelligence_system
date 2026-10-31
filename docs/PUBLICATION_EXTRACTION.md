# Verified publication extraction — 20 October 2026

The submission uses **`data/staging/batch_005_verified_publications`**, selected atomically by `data/staging/LATEST_ENRICHMENT`. It supersedes enrichment batches 002–004; those earlier snapshots are retained as history and must not be imported. Batch 003 was rejected by loader validation before any database writes because the provider duplicated one person in an author list. Batch 005 handles repeated author rows conservatively and includes all available second pages.

## Final numbers

| Evidence layer | Faculty | SCOPE | SCORE |
|---|---:|---:|---:|
| Official directory candidates | 337 | 222 | 115 |
| Verified OpenAlex identities with publications | **194** | **130** | **64** |

The verified subset has **4,391 distinct publication records since 2019**, **4,740 verified internal authorship links**, and **129 pairs of internal coauthors**. All 194 completed the provider-reported publication pagination. These are selected faculty, not an exhaustive school census or a claim that the remaining faculty have no publications.

| School | Official department | Faculty with verified publications |
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

## How identity and publications were collected

`scripts/enrich_directory.py` reads the separately extracted official VIT directory snapshot. Each accepted external identity requires an exact official ORCID, a compatible provider-displayed name, and OpenAlex affiliation evidence for Vellore Institute of Technology University (`I876193797`). Campus and school membership come from the official Vellore directory, since the OpenAlex institution represents the university. Names may reorder or expand an initial; fuzzy matching and guessed author searches are not used. Multiple observed ORCIDs and shared author identities enter review. Profile freshness on VIT was not validated; extraction of complete fields is not evidence that a VIT page is current.

The collector requests all works from 1 January 2019, with 100 results per page. It follows cursor pagination and uses the documented basic-page fallback when an unauthenticated cursor request is restricted and total depth is below 10,000. Three authors needed this fallback; their remaining 39, 48 and one papers were retrieved. No arbitrary 40-paper cap remains. Raw JSON responses, request URLs, retrieval times and SHA-256 hashes are preserved under `data/collection/enrichment_openalex_2026-10-20/responses/`.

Each publication retains its provider work ID, title, publication date/year, type, DOI, venue, dated citation count and complete provider raw-author list. Internal authorship is linked when OpenAlex lists an accepted author-profile ID. That match is at the author-record level: it does not prove each individual paper belongs to that person. Work-level affiliation may be absent, stale or wrong, so uncertain records should be checked before being presented as confirmed. Exact DOI duplicates are suppressed. Repeated provider author rows produce one person–paper relationship with unknown author order rather than a guessed position; the raw list remains available. Missing publication titles enter review. Provider metadata is evidence rather than an independently audited bibliography.

OpenAlex supplies h-index, i10-index, citation totals and work totals. These are stored as **OpenAlex career snapshots**, with their collection date. The official VIT page's displayed metrics remain separate and do not inherit the OpenAlex label. Imported since-2019 paper counts are separate from career totals. No Google Scholar scraping was performed; Scholar and ORCID remain outbound profile links.

## Review and missing coverage

143 candidates are held from external publication linking: 84 ORCIDs did not resolve in OpenAlex during the online run, 27 displayed-name conflicts, 18 without VIT affiliation evidence, nine multi-ORCID profiles needing review, and five without an ORCID. The cache-only final replay labels the original 84 missing author responses `NO_CACHED_RESPONSE`; their original online `ORCID_NOT_FOUND` decisions are retained in batch 002's review file. An absent OpenAlex record does not imply a broken ORCID page or zero publications.

Known work-level review signal: OpenAlex lists Sweta Bhattacharya’s ORCID on the 2024 caecilian paper “A note on the larval stage of the Sikkimese caecilian…” without an affiliation for her on that work. It may be valid; it has not been confirmed and should not be presented as a settled coauthorship. The author-profile match did not include manual paper-by-paper checking.

No lab memberships, supervision, research quality, availability for collaboration or publication impact factors were inferred. Suggestions may use explicit official research areas, publication keywords and these verified coauthor links. A missing path means no path found in this collected subset.

## Reproduce and verify

Run `python scripts/enrich_directory.py --offline --output data/staging/NEW_BATCH_ID` to replay existing cached evidence without network access. Omit `--offline` for an explicit provider refresh. The collector refuses to overwrite an existing output folder and writes the checksum manifest last. Review and validate any new batch before changing `LATEST_ENRICHMENT`; collection never changes that pointer automatically.

Six focused offline tests cover reordered names and initials, mismatched identities, missing VIT affiliation, pagination beyond 100 papers, restricted cursor fallback, and duplicated provider authors. They pass with `python -m pytest tests/test_author_identity.py -q`. The final batch additionally passed the actual loader's closed-manifest/checksum validation and independent foreign-reference, unique authorship, DOI uniqueness and title checks.

Official API references: [author fields and limitations](https://help.openalex.org/data/authors/), [supported pagination](https://help.openalex.org/api/paging/).
