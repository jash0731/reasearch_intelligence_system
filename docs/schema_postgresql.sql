-- Initial schema: fresh PostgreSQL database only.
-- Generated from research/database/models.py and sql.py; PostgreSQL 16.
-- Includes 23 tables, four discovery views, distance function, audit trigger and indexes.
BEGIN;
DO $$ BEGIN
 IF current_database() !~ '_(app|test)$' THEN
  RAISE EXCEPTION 'Refused: use a separate database ending _app or _test';
 END IF;
 IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE') THEN
  RAISE EXCEPTION 'Refused: initial migration requires an empty schema';
 END IF;
END $$;

CREATE TABLE publication_audit (
	id SERIAL NOT NULL, 
	publication_id INTEGER NOT NULL, 
	operation VARCHAR(10) NOT NULL, 
	old_row JSONB, 
	new_row JSONB, 
	changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_publication_audit PRIMARY KEY (id), 
	CONSTRAINT valid_audit_operation CHECK (operation IN ('INSERT','UPDATE','DELETE'))
);

CREATE TABLE research_area (
	id SERIAL NOT NULL, 
	name TEXT NOT NULL, 
	normalized_term TEXT NOT NULL, 
	CONSTRAINT pk_research_area PRIMARY KEY (id), 
	CONSTRAINT uq_research_area_normalized_term UNIQUE (normalized_term)
);

CREATE TABLE school (
	id SERIAL NOT NULL, 
	code VARCHAR(10) NOT NULL, 
	name TEXT NOT NULL, 
	campus VARCHAR(40) DEFAULT 'Vellore' NOT NULL, 
	CONSTRAINT pk_school PRIMARY KEY (id), 
	CONSTRAINT supported_school CHECK (code IN ('SCOPE','SCORE')), 
	CONSTRAINT vellore_only CHECK (campus='Vellore'), 
	CONSTRAINT uq_school_code UNIQUE (code)
);

CREATE TABLE source_record (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	source_type VARCHAR(40) NOT NULL, 
	url TEXT NOT NULL, 
	retrieved_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	report_month VARCHAR(7), 
	content_sha256 VARCHAR(64), 
	cache_reference TEXT, 
	payload JSONB NOT NULL, 
	CONSTRAINT pk_source_record PRIMARY KEY (id), 
	CONSTRAINT valid_source_type CHECK (source_type IN ('DIRECTORY','RESEARCH_PROFILE','EMAIL','PDF','API','MANUAL')), 
	CONSTRAINT uq_source_record_source_key UNIQUE (source_key)
);

CREATE TABLE department (
	id SERIAL NOT NULL, 
	school_id INTEGER NOT NULL, 
	code VARCHAR(120) NOT NULL, 
	name TEXT NOT NULL, 
	CONSTRAINT pk_department PRIMARY KEY (id), 
	CONSTRAINT uq_department_school_id_code UNIQUE (school_id, code), 
	CONSTRAINT uq_department_school_id_name UNIQUE (school_id, name), 
	CONSTRAINT fk_department_school_id_school FOREIGN KEY(school_id) REFERENCES school (id) ON DELETE RESTRICT
);

CREATE TABLE lab (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	name TEXT NOT NULL, 
	school_id INTEGER, 
	description TEXT, 
	official_url TEXT, 
	contact_email TEXT, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_lab PRIMARY KEY (id), 
	CONSTRAINT uq_lab_source_key UNIQUE (source_key), 
	CONSTRAINT fk_lab_school_id_school FOREIGN KEY(school_id) REFERENCES school (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_lab_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE patent (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	title TEXT NOT NULL, 
	application_no TEXT, 
	patent_no TEXT, 
	status VARCHAR(20) NOT NULL, 
	event_date DATE, 
	report_month VARCHAR(7), 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_patent PRIMARY KEY (id), 
	CONSTRAINT valid_patent_status CHECK (status IN ('FILED','PUBLISHED','GRANTED')), 
	CONSTRAINT uq_patent_source_key UNIQUE (source_key), 
	CONSTRAINT fk_patent_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE project (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	title TEXT NOT NULL, 
	funder_name TEXT, 
	kind VARCHAR(40), 
	source_reported_status VARCHAR(40), 
	status_as_of DATE, 
	start_date DATE, 
	end_date DATE, 
	official_url TEXT, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_project PRIMARY KEY (id), 
	CONSTRAINT uq_project_source_key UNIQUE (source_key), 
	CONSTRAINT fk_project_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE venue (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	name TEXT NOT NULL, 
	kind VARCHAR(40), 
	issn_l VARCHAR(30), 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_venue PRIMARY KEY (id), 
	CONSTRAINT uq_venue_source_key UNIQUE (source_key), 
	CONSTRAINT fk_venue_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE faculty (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	canonical_url TEXT NOT NULL, 
	name TEXT NOT NULL, 
	designation TEXT NOT NULL, 
	emp_id VARCHAR(40), 
	email TEXT, 
	department_id INTEGER, 
	source_id INTEGER NOT NULL, 
	publication_collection_status VARCHAR(30) DEFAULT 'NOT_ATTEMPTED' NOT NULL, 
	CONSTRAINT pk_faculty PRIMARY KEY (id), 
	CONSTRAINT valid_collection_status CHECK (publication_collection_status IN ('NOT_ATTEMPTED','IDENTITY_REVIEW','FETCH_FAILED','PARTIAL','RETRIEVED')), 
	CONSTRAINT uq_faculty_source_key UNIQUE (source_key), 
	CONSTRAINT uq_faculty_canonical_url UNIQUE (canonical_url), 
	CONSTRAINT uq_faculty_emp_id UNIQUE (emp_id), 
	CONSTRAINT fk_faculty_department_id_department FOREIGN KEY(department_id) REFERENCES department (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_faculty_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE lab_research_area (
	lab_id INTEGER NOT NULL, 
	area_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	assignment_method VARCHAR(40) NOT NULL, 
	CONSTRAINT pk_lab_research_area PRIMARY KEY (lab_id, area_id), 
	CONSTRAINT valid_lab_research_area_method CHECK (assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW','LITERAL_KEYWORD','AUTHOR_INTEREST_INFERRED')), 
	CONSTRAINT fk_lab_research_area_lab_id_lab FOREIGN KEY(lab_id) REFERENCES lab (id) ON DELETE CASCADE, 
	CONSTRAINT fk_lab_research_area_area_id_research_area FOREIGN KEY(area_id) REFERENCES research_area (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_lab_research_area_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_lab_research_area_area_owner ON lab_research_area (area_id, lab_id);

CREATE TABLE project_research_area (
	project_id INTEGER NOT NULL, 
	area_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	assignment_method VARCHAR(40) NOT NULL, 
	CONSTRAINT pk_project_research_area PRIMARY KEY (project_id, area_id), 
	CONSTRAINT valid_project_research_area_method CHECK (assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW','LITERAL_KEYWORD','AUTHOR_INTEREST_INFERRED')), 
	CONSTRAINT fk_project_research_area_project_id_project FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE, 
	CONSTRAINT fk_project_research_area_area_id_research_area FOREIGN KEY(area_id) REFERENCES research_area (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_project_research_area_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_project_research_area_area_owner ON project_research_area (area_id, project_id);

CREATE TABLE publication (
	id SERIAL NOT NULL, 
	source_key TEXT NOT NULL, 
	doi TEXT, 
	title TEXT NOT NULL, 
	year INTEGER, 
	publication_date DATE, 
	kind VARCHAR(40) NOT NULL, 
	venue_id INTEGER, 
	abstract TEXT, 
	raw_authors TEXT, 
	citations INTEGER, 
	citations_provider VARCHAR(100), 
	citations_observed_at TIMESTAMP WITH TIME ZONE, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_publication PRIMARY KEY (id), 
	CONSTRAINT valid_publication_year CHECK (year BETWEEN 1900 AND 2100), 
	CONSTRAINT nonnegative_publication_citations CHECK (citations >= 0), 
	CONSTRAINT uq_publication_source_key UNIQUE (source_key), 
	CONSTRAINT uq_publication_doi UNIQUE (doi), 
	CONSTRAINT fk_publication_venue_id_venue FOREIGN KEY(venue_id) REFERENCES venue (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_publication_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_publication_year ON publication (year);

CREATE TABLE faculty_external_profile (
	id SERIAL NOT NULL, 
	faculty_id INTEGER NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	external_id TEXT NOT NULL, 
	url TEXT NOT NULL, 
	identity_match_status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, 
	checked_at TIMESTAMP WITH TIME ZONE, 
	resolution_evidence TEXT, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_external_profile PRIMARY KEY (id), 
	CONSTRAINT uq_faculty_external_profile_faculty_id_provider_external_id UNIQUE (faculty_id, provider, external_id), 
	CONSTRAINT valid_identity_match_status CHECK (identity_match_status IN ('PENDING','VERIFIED','CONFLICT')), 
	CONSTRAINT fk_faculty_external_profile_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_external_profile_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_verified_external_identity ON faculty_external_profile (provider, external_id) WHERE identity_match_status = 'VERIFIED';

CREATE TABLE faculty_lab (
	faculty_id INTEGER NOT NULL, 
	lab_id INTEGER NOT NULL, 
	membership_role TEXT, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_lab PRIMARY KEY (faculty_id, lab_id), 
	CONSTRAINT fk_faculty_lab_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_faculty_lab_lab_id_lab FOREIGN KEY(lab_id) REFERENCES lab (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_lab_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE faculty_metric_snapshot (
	id SERIAL NOT NULL, 
	faculty_id INTEGER NOT NULL, 
	provider VARCHAR(120) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metric_as_of DATE, 
	h_index INTEGER, 
	i10_index INTEGER, 
	cited_by_count INTEGER, 
	works_count INTEGER, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_metric_snapshot PRIMARY KEY (id), 
	CONSTRAINT uq_faculty_metric_snapshot_faculty_id_provider_source_id UNIQUE (faculty_id, provider, source_id), 
	CONSTRAINT nonnegative_author_metrics CHECK (h_index >= 0 AND i10_index >= 0 AND cited_by_count >= 0 AND works_count >= 0), 
	CONSTRAINT fk_faculty_metric_snapshot_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_metric_snapshot_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE faculty_project (
	faculty_id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	participation_role TEXT, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_project PRIMARY KEY (faculty_id, project_id), 
	CONSTRAINT fk_faculty_project_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_faculty_project_project_id_project FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_project_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE faculty_publication (
	faculty_id INTEGER NOT NULL, 
	publication_id INTEGER NOT NULL, 
	author_order INTEGER, 
	is_corresponding BOOLEAN, 
	identity_match_status VARCHAR(20) NOT NULL, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_publication PRIMARY KEY (faculty_id, publication_id), 
	CONSTRAINT uq_faculty_publication_publication_id_author_order UNIQUE (publication_id, author_order), 
	CONSTRAINT positive_author_order CHECK (author_order > 0), 
	CONSTRAINT verified_authorship_only CHECK (identity_match_status='VERIFIED'), 
	CONSTRAINT fk_faculty_publication_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_faculty_publication_publication_id_publication FOREIGN KEY(publication_id) REFERENCES publication (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_publication_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_authorship_publication_faculty ON faculty_publication (publication_id, faculty_id);

CREATE TABLE faculty_qualification (
	id SERIAL NOT NULL, 
	faculty_id INTEGER NOT NULL, 
	source_key TEXT NOT NULL, 
	qualification TEXT NOT NULL, 
	institution TEXT, 
	specialization TEXT, 
	graduation_year INTEGER, 
	source_text TEXT NOT NULL, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_faculty_qualification PRIMARY KEY (id), 
	CONSTRAINT valid_graduation_year CHECK (graduation_year BETWEEN 1900 AND 2100), 
	CONSTRAINT fk_faculty_qualification_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE CASCADE, 
	CONSTRAINT uq_faculty_qualification_source_key UNIQUE (source_key), 
	CONSTRAINT fk_faculty_qualification_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE faculty_research_area (
	faculty_id INTEGER NOT NULL, 
	area_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	assignment_method VARCHAR(40) NOT NULL, 
	CONSTRAINT pk_faculty_research_area PRIMARY KEY (faculty_id, area_id), 
	CONSTRAINT valid_faculty_research_area_method CHECK (assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW','LITERAL_KEYWORD','AUTHOR_INTEREST_INFERRED')), 
	CONSTRAINT fk_faculty_research_area_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE CASCADE, 
	CONSTRAINT fk_faculty_research_area_area_id_research_area FOREIGN KEY(area_id) REFERENCES research_area (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_faculty_research_area_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_faculty_research_area_area_owner ON faculty_research_area (area_id, faculty_id);

CREATE TABLE patent_inventor (
	faculty_id INTEGER NOT NULL, 
	patent_id INTEGER NOT NULL, 
	evidence_kind VARCHAR(40) NOT NULL, 
	source_id INTEGER NOT NULL, 
	CONSTRAINT pk_patent_inventor PRIMARY KEY (faculty_id, patent_id), 
	CONSTRAINT fk_patent_inventor_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_patent_inventor_patent_id_patent FOREIGN KEY(patent_id) REFERENCES patent (id) ON DELETE CASCADE, 
	CONSTRAINT fk_patent_inventor_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE TABLE publication_research_area (
	publication_id INTEGER NOT NULL, 
	area_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	assignment_method VARCHAR(40) NOT NULL, 
	CONSTRAINT pk_publication_research_area PRIMARY KEY (publication_id, area_id), 
	CONSTRAINT valid_publication_research_area_method CHECK (assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW','LITERAL_KEYWORD','AUTHOR_INTEREST_INFERRED')), 
	CONSTRAINT fk_publication_research_area_publication_id_publication FOREIGN KEY(publication_id) REFERENCES publication (id) ON DELETE CASCADE, 
	CONSTRAINT fk_publication_research_area_area_id_research_area FOREIGN KEY(area_id) REFERENCES research_area (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_publication_research_area_source_id_source_record FOREIGN KEY(source_id) REFERENCES source_record (id) ON DELETE RESTRICT
);

CREATE INDEX ix_publication_research_area_area_owner ON publication_research_area (area_id, publication_id);

CREATE TABLE user_account (
	id SERIAL NOT NULL, 
	username VARCHAR(100) NOT NULL, 
	password_hash TEXT NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	faculty_id INTEGER, 
	CONSTRAINT pk_user_account PRIMARY KEY (id), 
	CONSTRAINT faculty_only_user_roles CHECK (role IN ('ADMIN','HOD','FACULTY')), 
	CONSTRAINT linked_faculty_account CHECK (faculty_id IS NOT NULL OR role='ADMIN'), 
	CONSTRAINT uq_user_account_username UNIQUE (username), 
	CONSTRAINT uq_user_account_faculty_id UNIQUE (faculty_id), 
	CONSTRAINT fk_user_account_faculty_id_faculty FOREIGN KEY(faculty_id) REFERENCES faculty (id) ON DELETE RESTRICT
);

CREATE VIEW v_coauthor_edge AS 
 SELECT a.faculty_id AS faculty_a,b.faculty_id AS faculty_b,
        COUNT(DISTINCT a.publication_id) AS shared_papers,MAX(p.year) AS latest_year
 FROM faculty_publication a
 JOIN faculty_publication b ON b.publication_id=a.publication_id AND a.faculty_id<b.faculty_id
 JOIN publication p ON p.id=a.publication_id
 WHERE a.identity_match_status='VERIFIED' AND b.identity_match_status='VERIFIED'
 GROUP BY a.faculty_id,b.faculty_id;

CREATE VIEW v_shared_research_area AS 
 SELECT a.faculty_id AS faculty_a,b.faculty_id AS faculty_b,
        COUNT(DISTINCT a.area_id) AS shared_areas
 FROM faculty_research_area a
 JOIN faculty_research_area b ON b.area_id=a.area_id AND a.faculty_id<b.faculty_id
 WHERE a.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
   AND b.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
 GROUP BY a.faculty_id,b.faculty_id;

CREATE VIEW v_faculty_discovery AS 
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
 LEFT JOIN topics t ON t.faculty_id=f.id LEFT JOIN labs l ON l.faculty_id=f.id;

CREATE VIEW v_lab_discovery AS 
 WITH members AS (SELECT lab_id,COUNT(*) AS count FROM faculty_lab GROUP BY lab_id),
 topics AS (SELECT lab_id,COUNT(*) AS count FROM lab_research_area GROUP BY lab_id)
 SELECT l.id AS lab_id,l.name,l.official_url,l.contact_email,s.code AS school_code,
        COALESCE(m.count,0) AS documented_member_count,COALESCE(t.count,0) AS documented_area_count
 FROM lab l LEFT JOIN school s ON s.id=l.school_id
 LEFT JOIN members m ON m.lab_id=l.id LEFT JOIN topics t ON t.lab_id=l.id;


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
$$;


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
END; $$;

CREATE TRIGGER trg_publication_audit AFTER INSERT OR UPDATE OR DELETE ON publication FOR EACH ROW EXECUTE FUNCTION audit_publication();

COMMIT;
