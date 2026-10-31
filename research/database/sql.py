"""PostgreSQL discovery views, path queries and publication auditing."""
from sqlalchemy import inspect, text
from .models import metadata

VIEWS={
 'v_coauthor_edge': '''
 SELECT a.faculty_id AS faculty_a,b.faculty_id AS faculty_b,
        COUNT(DISTINCT a.publication_id) AS shared_papers,MAX(p.year) AS latest_year
 FROM faculty_publication a
 JOIN faculty_publication b ON b.publication_id=a.publication_id AND a.faculty_id<b.faculty_id
 JOIN publication p ON p.id=a.publication_id
 WHERE a.identity_match_status='VERIFIED' AND b.identity_match_status='VERIFIED'
 GROUP BY a.faculty_id,b.faculty_id''',
 'v_shared_research_area': '''
 SELECT a.faculty_id AS faculty_a,b.faculty_id AS faculty_b,
        COUNT(DISTINCT a.area_id) AS shared_areas
 FROM faculty_research_area a
 JOIN faculty_research_area b ON b.area_id=a.area_id AND a.faculty_id<b.faculty_id
 WHERE a.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
   AND b.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
 GROUP BY a.faculty_id,b.faculty_id''',
 'v_faculty_discovery': '''
 WITH papers AS (SELECT faculty_id,COUNT(DISTINCT publication_id) AS count
                FROM faculty_publication GROUP BY faculty_id),
 topics AS (SELECT faculty_id,COUNT(*) AS count FROM faculty_research_area GROUP BY faculty_id),
 labs AS (SELECT faculty_id,COUNT(*) AS count FROM faculty_lab GROUP BY faculty_id)
 SELECT f.id AS faculty_id,f.name,f.designation,f.canonical_url,f.email,
        d.id AS department_id,d.name AS department_name,s.code AS school_code,
        f.publication_collection_status,
        CASE WHEN f.publication_collection_status IN ('PARTIAL','RETRIEVED')
             THEN COALESCE(p.count,0) ELSE NULL END AS loaded_publication_count,
        COALESCE(t.count,0) AS declared_area_count,COALESCE(l.count,0) AS documented_lab_count
 FROM faculty f LEFT JOIN department d ON d.id=f.department_id
 LEFT JOIN school s ON s.id=d.school_id LEFT JOIN papers p ON p.faculty_id=f.id
 LEFT JOIN topics t ON t.faculty_id=f.id LEFT JOIN labs l ON l.faculty_id=f.id''',
 'v_lab_discovery': '''
 WITH members AS (SELECT lab_id,COUNT(*) AS count FROM faculty_lab GROUP BY lab_id),
 topics AS (SELECT lab_id,COUNT(*) AS count FROM lab_research_area GROUP BY lab_id)
 SELECT l.id AS lab_id,l.name,l.official_url,l.contact_email,s.code AS school_code,
        COALESCE(m.count,0) AS documented_member_count,COALESCE(t.count,0) AS documented_area_count
 FROM lab l LEFT JOIN school s ON s.id=l.school_id
 LEFT JOIN members m ON m.lab_id=l.id LEFT JOIN topics t ON t.lab_id=l.id''',
}

TWO_HOP_PATHS='''
WITH edges AS (
 SELECT DISTINCT ON (a.faculty_id,b.faculty_id)
        a.faculty_id AS source,b.faculty_id AS target,a.publication_id
 FROM faculty_publication a JOIN faculty_publication b
 ON a.publication_id=b.publication_id AND a.faculty_id<>b.faculty_id
 JOIN publication p ON p.id=a.publication_id
 ORDER BY a.faculty_id,b.faculty_id,p.year DESC NULLS LAST,p.id
), direct AS (SELECT DISTINCT target FROM edges WHERE source=:faculty_id)
SELECT DISTINCT second.target AS candidate_id,first.target AS intermediary_id,
       first.publication_id AS first_publication_id,second.publication_id AS second_publication_id
FROM edges first JOIN edges second ON first.target=second.source
WHERE first.source=:faculty_id AND second.target<>:faculty_id
 AND second.target NOT IN (SELECT target FROM direct)
ORDER BY candidate_id,intermediary_id,first_publication_id,second_publication_id
'''

SHARED_AREAS='''
SELECT other.faculty_id,COUNT(DISTINCT other.area_id) AS shared_area_count
FROM faculty_research_area mine JOIN faculty_research_area other ON mine.area_id=other.area_id
WHERE mine.faculty_id=:faculty_id AND other.faculty_id<>:faculty_id
 AND mine.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
 AND other.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
GROUP BY other.faculty_id ORDER BY shared_area_count DESC,other.faculty_id
'''

DISTANCE_FUNCTION='''
CREATE OR REPLACE FUNCTION fn_coauthor_distance(p_start INTEGER,p_end INTEGER,p_max_depth INTEGER DEFAULT 2)
RETURNS INTEGER LANGUAGE SQL STABLE AS $$
 WITH RECURSIVE edges AS (
   SELECT faculty_a AS source,faculty_b AS target FROM v_coauthor_edge
   UNION ALL SELECT faculty_b,faculty_a FROM v_coauthor_edge
 ), paths(node,visited,depth) AS (
   SELECT id,ARRAY[id],0 FROM faculty WHERE id=p_start
   UNION ALL
   SELECT e.target,p.visited||e.target,p.depth+1 FROM paths p JOIN edges e ON e.source=p.node
   WHERE p.depth<p_max_depth AND p_max_depth BETWEEN 1 AND 2 AND NOT e.target=ANY(p.visited)
 ) SELECT MIN(depth)::INTEGER FROM paths
   WHERE node=p_end AND p_max_depth BETWEEN 1 AND 2;
$$'''

AUDIT_FUNCTION='''
CREATE OR REPLACE FUNCTION audit_publication()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   INSERT INTO publication_audit(publication_id,operation,old_row) VALUES(OLD.id,TG_OP,to_jsonb(OLD));
   RETURN OLD;
 ELSIF TG_OP='INSERT' THEN
   INSERT INTO publication_audit(publication_id,operation,new_row) VALUES(NEW.id,TG_OP,to_jsonb(NEW));
 ELSE
   INSERT INTO publication_audit(publication_id,operation,old_row,new_row) VALUES(NEW.id,TG_OP,to_jsonb(OLD),to_jsonb(NEW));
 END IF;
 RETURN NEW;
END; $$'''


def initialize_schema(engine):
    """Create an empty application schema or refresh its views; refuse foreign schemas."""
    if engine.dialect.name!='postgresql':
        raise ValueError('Application schema requires PostgreSQL')
    with engine.begin() as connection:
        existing=set(inspect(connection).get_table_names())
        if existing and existing!=set(metadata.tables):
            raise ValueError('Target is not an empty or complete application schema; existing tables were preserved')
        if existing:
            for name,table in metadata.tables.items():
                if {c['name'] for c in inspect(connection).get_columns(name)}!=set(table.c.keys()):
                    raise ValueError('Incompatible application columns; use a reviewed migration')
        metadata.create_all(connection)
        for name,query in VIEWS.items():
            connection.execute(text(f'CREATE OR REPLACE VIEW {name} AS {query}'))
        connection.execute(text(DISTANCE_FUNCTION))
        connection.execute(text(AUDIT_FUNCTION))
        connection.execute(text('DROP TRIGGER IF EXISTS trg_publication_audit ON publication'))
        connection.execute(text('CREATE TRIGGER trg_publication_audit AFTER INSERT OR UPDATE OR DELETE ON publication FOR EACH ROW EXECUTE FUNCTION audit_publication()'))
