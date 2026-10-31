-- Fifteen read-only PostgreSQL examples for the current collaboration schema.
-- Run: psql -v ON_ERROR_STOP=1 -d vit_research_app -f docs/SQL_SHOWCASE.sql
-- A selected faculty is chosen reproducibly within each query; no hard-coded app IDs.

-- 01. Curated faculty coverage, grouped by school (not university headcount).
SELECT s.code AS school,COUNT(f.id) AS selected_faculty
FROM school s JOIN department d ON d.school_id=s.id
LEFT JOIN faculty f ON f.department_id=d.id
GROUP BY s.code ORDER BY s.code;

-- 02. Department coverage and publication collection status; unknown output stays unknown.
SELECT school_code,department_name,COUNT(*) AS faculty,
 COUNT(loaded_publication_count) AS faculty_with_retrieved_records,
 SUM(loaded_publication_count) AS loaded_authorships
FROM v_faculty_discovery GROUP BY school_code,department_name
ORDER BY school_code,department_name;

-- 03. Academic qualifications with official source evidence, via a multi-table join.
SELECT f.name,q.qualification,q.institution,q.graduation_year,s.url AS official_source
FROM faculty f JOIN faculty_qualification q ON q.faculty_id=f.id
JOIN source_record s ON s.id=q.source_id
ORDER BY f.name,q.graduation_year NULLS LAST LIMIT 40;

-- 04. Claimed versus verified provider identities are separate states.
SELECT provider,identity_match_status,COUNT(*) AS profile_links
FROM faculty_external_profile GROUP BY provider,identity_match_status
ORDER BY provider,identity_match_status;

-- 05. Candidate collaborators through exact, sourced shared areas (no similarity model).
WITH chosen AS (SELECT MIN(id) AS id FROM faculty)
SELECT other.name,COUNT(DISTINCT a.area_id) AS shared_area_count,
 STRING_AGG(DISTINCT area.name,', ' ORDER BY area.name) AS shared_areas
FROM chosen c JOIN faculty_research_area a ON a.faculty_id=c.id
JOIN faculty_research_area b ON b.area_id=a.area_id AND b.faculty_id<>c.id
JOIN faculty other ON other.id=b.faculty_id JOIN research_area area ON area.id=a.area_id
WHERE a.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
 AND b.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
GROUP BY other.id,other.name HAVING COUNT(DISTINCT a.area_id)>=1
ORDER BY shared_area_count DESC,other.name LIMIT 30;

-- 06. Literal keyword filter with papers as evidence; the term can be a bound app parameter.
SELECT f.name,p.title,p.year,p.doi,s.url AS evidence
FROM publication p JOIN faculty_publication fp ON fp.publication_id=p.id
JOIN faculty f ON f.id=fp.faculty_id JOIN source_record s ON s.id=p.source_id
WHERE POSITION('learning' IN LOWER(p.title))>0
ORDER BY p.year DESC NULLS LAST,p.title LIMIT 30;

-- 07. Direct coauthors and distinct shared-paper counts from an authorship self-join view.
SELECT a.name AS first_author,b.name AS second_author,e.shared_papers,e.latest_year
FROM v_coauthor_edge e JOIN faculty a ON a.id=e.faculty_a JOIN faculty b ON b.id=e.faculty_b
ORDER BY e.shared_papers DESC,a.name,b.name LIMIT 30;

-- 08. Two-hop introductions with both actual papers; excludes self and direct coauthors.
WITH chosen AS (
 SELECT faculty_id AS id FROM faculty_publication GROUP BY faculty_id ORDER BY COUNT(*) DESC,faculty_id LIMIT 1
), edges AS (
 SELECT DISTINCT ON (a.faculty_id,b.faculty_id)
 a.faculty_id AS source,b.faculty_id AS target,a.publication_id
 FROM faculty_publication a JOIN faculty_publication b
 ON a.publication_id=b.publication_id AND a.faculty_id<>b.faculty_id
 JOIN publication p ON p.id=a.publication_id
 ORDER BY a.faculty_id,b.faculty_id,p.year DESC NULLS LAST,p.id
), paths AS (
 SELECT DISTINCT e2.target AS candidate,e1.target AS intermediary,
 e1.publication_id AS first_paper,e2.publication_id AS second_paper
 FROM chosen c JOIN edges e1 ON e1.source=c.id JOIN edges e2 ON e2.source=e1.target
 WHERE e2.target<>c.id AND NOT EXISTS(SELECT 1 FROM edges d WHERE d.source=c.id AND d.target=e2.target)
)
SELECT candidate.name AS suggested_person,intermediary.name AS introduction_through,
 p1.title AS your_shared_paper,p2.title AS their_shared_paper
FROM paths x JOIN faculty candidate ON candidate.id=x.candidate
JOIN faculty intermediary ON intermediary.id=x.intermediary
JOIN publication p1 ON p1.id=x.first_paper JOIN publication p2 ON p2.id=x.second_paper
ORDER BY candidate.name,intermediary.name,p1.title,p2.title LIMIT 30;

-- 09. Official labs, separately counting documented members and declared areas.
SELECT name,school_code,documented_member_count,documented_area_count,official_url
FROM v_lab_discovery ORDER BY school_code,name;

-- 10. Profile-listed project observations and participants, without asserting current status.
SELECT p.title,p.kind,p.source_reported_status,p.status_as_of,
 STRING_AGG(f.name,', ' ORDER BY f.name) AS listed_participants,s.url AS official_source
FROM project p JOIN faculty_project fp ON fp.project_id=p.id
JOIN faculty f ON f.id=fp.faculty_id JOIN source_record s ON s.id=p.source_id
GROUP BY p.id,s.url ORDER BY p.title LIMIT 30;

-- 11. Latest metric observation per faculty AND provider; preserve provider boundaries.
WITH ranked AS (
 SELECT m.*,ROW_NUMBER() OVER(PARTITION BY faculty_id,provider ORDER BY observed_at DESC,id DESC) AS rn
 FROM faculty_metric_snapshot m
)
SELECT f.name,r.provider,r.h_index,r.i10_index,r.cited_by_count,r.observed_at,r.metric_as_of
FROM ranked r JOIN faculty f ON f.id=r.faculty_id WHERE rn=1
ORDER BY f.name,r.provider LIMIT 40;

-- 12. Annual loaded-work counts and LAG window function; incomplete corpus is explicit.
WITH annual AS (SELECT year,COUNT(*) AS loaded_publications FROM publication WHERE year IS NOT NULL GROUP BY year)
SELECT year,loaded_publications,LAG(loaded_publications) OVER(ORDER BY year) AS previous_loaded_year,
 loaded_publications-LAG(loaded_publications) OVER(ORDER BY year) AS loaded_count_change
FROM annual ORDER BY year;

-- 13. Venues used by researchers in a declared area (frequency, not acceptance advice).
SELECT area.name AS declared_area,v.name AS venue,COUNT(DISTINCT p.id) AS loaded_works
FROM research_area area JOIN faculty_research_area fa ON fa.area_id=area.id
JOIN faculty_publication fp ON fp.faculty_id=fa.faculty_id
JOIN publication p ON p.id=fp.publication_id JOIN venue v ON v.id=p.venue_id
WHERE area.normalized_term='machine learning' AND fa.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
GROUP BY area.name,v.id,v.name ORDER BY loaded_works DESC,v.name LIMIT 20;

-- 14. Stored function: bounded coauthorship distance; NULL is no collected path.
WITH chosen AS (SELECT faculty_id AS id FROM faculty_publication GROUP BY faculty_id ORDER BY COUNT(*) DESC,faculty_id LIMIT 1)
SELECT f.name,fn_coauthor_distance(c.id,f.id,2) AS distance
FROM chosen c CROSS JOIN faculty f WHERE f.id<>c.id
ORDER BY distance NULLS LAST,f.name LIMIT 30;

-- 15. Data-quality audit of collection states alongside trigger history (not missing=zero).
SELECT f.publication_collection_status,COUNT(*) AS selected_faculty,
 COUNT(v.loaded_publication_count) AS faculty_with_known_loaded_counts,
 (SELECT COUNT(*) FROM publication_audit) AS publication_change_events
FROM faculty f JOIN v_faculty_discovery v ON v.faculty_id=f.id
GROUP BY f.publication_collection_status ORDER BY f.publication_collection_status;
