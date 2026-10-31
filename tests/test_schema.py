"""PostgreSQL integration checks for the collaboration-discovery schema."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text, inspect
from sqlalchemy.exc import IntegrityError
from research.database import models as m
from research.database.loader import load_directory
from research.database.sql import initialize_schema, TWO_HOP_PATHS, SHARED_AREAS

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def schema_engine(postgres_database_factory):
    with postgres_database_factory() as uri:
        engine=create_engine(uri)
        initialize_schema(engine)
        yield engine
        engine.dispose()


def seed_graph(db):
    source=db.execute(m.source_record.insert().values(source_key='fixture',source_type='MANUAL',
        url='https://example.org/evidence',retrieved_at=datetime.now(timezone.utc),payload={}).returning(m.source_record.c.id)).scalar_one()
    ids=[]
    for name in ['Alice','Bea','Chen','Dev']:
        ids.append(db.execute(m.faculty.insert().values(source_key=name,canonical_url='https://example.org/'+name,
            name=name,designation='Professor',source_id=source).returning(m.faculty.c.id)).scalar_one())
    works=[]
    for title in ['Alice and Bea','Bea and Chen','Alice and Bea again']:
        works.append(db.execute(m.publication.insert().values(source_key=title,title=title,kind='Journal',year=2025,
            source_id=source).returning(m.publication.c.id)).scalar_one())
    for paper,pair in zip(works,[(ids[0],ids[1]),(ids[1],ids[2]),(ids[0],ids[1])]):
        for order,faculty in enumerate(pair,1):
            db.execute(m.faculty_publication.insert().values(faculty_id=faculty,publication_id=paper,author_order=order,
                identity_match_status='VERIFIED',source_id=source))
    area=db.execute(m.research_area.insert().values(name='Database Systems',normalized_term='database systems').returning(m.research_area.c.id)).scalar_one()
    for person,method in zip(ids,['SOURCE_DECLARED','MANUAL_REVIEW','SOURCE_DECLARED','AUTHOR_INTEREST_INFERRED']):
        db.execute(m.faculty_research_area.insert().values(faculty_id=person,area_id=area,source_id=source,assignment_method=method))
    return source,ids,works


def test_views_paths_and_distance_are_witnessed(schema_engine):
    with schema_engine.begin() as db:
        source,ids,works=seed_graph(db)
        direct=db.execute(text('SELECT shared_papers FROM v_coauthor_edge WHERE faculty_a=:a AND faculty_b=:b'),dict(a=ids[0],b=ids[1])).scalar_one()
        assert direct==2
        paths=db.execute(text(TWO_HOP_PATHS),{'faculty_id':ids[0]}).mappings().all()
        assert {(p['candidate_id'],p['intermediary_id'],p['first_publication_id'],p['second_publication_id']) for p in paths}=={
            (ids[2],ids[1],works[0],works[1])}
        matches=db.execute(text(SHARED_AREAS),{'faculty_id':ids[0]}).mappings().all()
        assert {r['faculty_id'] for r in matches}=={ids[1],ids[2]}
        assert [db.execute(text('SELECT fn_coauthor_distance(:a,:b)'),dict(a=ids[0],b=p)).scalar_one() for p in ids]==[0,1,2,None]
        assert db.execute(text('SELECT fn_coauthor_distance(:a,:b,1)'),dict(a=ids[0],b=ids[2])).scalar_one() is None
        assert db.execute(text('SELECT fn_coauthor_distance(:a,:b,3)'),dict(a=ids[0],b=ids[2])).scalar_one() is None


def test_missing_publications_are_not_zero_and_audit_is_complete(schema_engine):
    with schema_engine.begin() as db:
        _,ids,works=seed_graph(db)
        assert db.execute(text('SELECT loaded_publication_count FROM v_faculty_discovery WHERE faculty_id=:id'),{'id':ids[3]}).scalar_one() is None
        db.execute(m.faculty.update().where(m.faculty.c.id==ids[3]).values(publication_collection_status='RETRIEVED'))
        assert db.execute(text('SELECT loaded_publication_count FROM v_faculty_discovery WHERE faculty_id=:id'),{'id':ids[3]}).scalar_one()==0
        db.execute(m.publication.update().where(m.publication.c.id==works[0]).values(title='Edited title'))
        db.execute(m.publication.delete().where(m.publication.c.id==works[0]))
        audits=db.execute(select(m.publication_audit).where(m.publication_audit.c.publication_id==works[0]).order_by(m.publication_audit.c.id)).mappings().all()
        assert [a['operation'] for a in audits]==['INSERT','UPDATE','DELETE']
        assert audits[1]['old_row']['title']=='Alice and Bea'
        assert audits[1]['new_row']['title']=='Edited title'
        assert audits[2]['old_row']['title']=='Edited title'


def test_authorship_requires_verified_identity_and_original_order(schema_engine):
    with schema_engine.begin() as db:
        source,ids,works=seed_graph(db)
        with pytest.raises(IntegrityError),db.begin_nested():
            db.execute(m.faculty_publication.insert().values(faculty_id=ids[3],publication_id=works[0],author_order=3,identity_match_status='PENDING',source_id=source))
        with pytest.raises(IntegrityError),db.begin_nested():
            db.execute(m.faculty_publication.insert().values(faculty_id=ids[3],publication_id=works[0],author_order=1,identity_match_status='VERIFIED',source_id=source))
        db.execute(m.faculty_publication.insert().values(faculty_id=ids[3],publication_id=works[0],author_order=8,identity_match_status='VERIFIED',source_id=source))


def test_verified_external_identity_cannot_belong_to_two_faculty(schema_engine):
    with schema_engine.begin() as db:
        source,ids,_=seed_graph(db)
        for faculty in ids[:2]:
            db.execute(m.faculty_external_profile.insert().values(faculty_id=faculty,provider='orcid',external_id='same',url='https://orcid.org/same',identity_match_status='PENDING',source_id=source))
        db.execute(m.faculty_external_profile.update().where(m.faculty_external_profile.c.faculty_id==ids[0]).values(identity_match_status='VERIFIED'))
        with pytest.raises(IntegrityError),db.begin_nested():
            db.execute(m.faculty_external_profile.update().where(m.faculty_external_profile.c.faculty_id==ids[1]).values(identity_match_status='VERIFIED'))


def test_directory_reload_is_idempotent_and_preserves_enrichment(schema_engine):
    batch=ROOT/'data/staging/batch_001_directory'
    with schema_engine.begin() as db:
        first=load_directory(db,batch)
        faculty_id=db.scalar(select(m.faculty.c.id).limit(1))
        db.execute(m.faculty.update().where(m.faculty.c.id==faculty_id).values(publication_collection_status='PARTIAL'))
        profile_id=db.scalar(select(m.faculty_external_profile.c.id).where(m.faculty_external_profile.c.faculty_id==faculty_id).limit(1))
        db.execute(m.faculty_external_profile.update().where(m.faculty_external_profile.c.id==profile_id).values(identity_match_status='VERIFIED'))
        second=load_directory(db,batch)
        assert first['counts']==second['counts']
        assert first['counts']['faculty']==337
        assert first['counts']['school']==2
        assert db.scalar(select(m.faculty.c.publication_collection_status).where(m.faculty.c.id==faculty_id))=='PARTIAL'
        assert db.scalar(select(m.faculty_external_profile.c.identity_match_status).where(m.faculty_external_profile.c.id==profile_id))=='VERIFIED'
        assert db.scalar(select(m.project.c.id).where(m.project.c.source_reported_status=='ONGOING').limit(1)) is not None
        assert db.scalar(select(m.faculty.c.emp_id).where(m.faculty.c.id==faculty_id)) is None
    initialize_schema(schema_engine)
    assert len(inspect(schema_engine).get_table_names())==23
    assert len(inspect(schema_engine).get_view_names())==4


def test_initializer_preserves_foreign_schema(postgres_database_factory):
    with postgres_database_factory() as uri:
        engine=create_engine(uri)
        with engine.begin() as db:db.execute(text('CREATE TABLE preserve_me (id INTEGER PRIMARY KEY)'))
        with pytest.raises(ValueError,match='preserved'):initialize_schema(engine)
        assert inspect(engine).get_table_names()==['preserve_me']
        engine.dispose()


def test_enrichment_has_source_metrics_verified_links_and_idempotent_audit(schema_engine,tmp_path):
    import hashlib,json
    from research.database.loader import load_enrichment
    captured='2026-10-20T04:00:00+00:00'
    with schema_engine.begin() as db:
        source,ids,_=seed_graph(db)
        db.execute(m.faculty.update().where(m.faculty.c.id==ids[0]).values(source_key='vit:profile:1'))
        data={'faculty':[{'source_key':'vit:profile:1','openalex_id':'https://openalex.org/A123',
            'source_url':'https://api.openalex.org/authors/A123','retrieved_at':captured,
            'identity_evidence':{'method':'official ORCID, matching name and VIT affiliation'},
            'publication_collection_status':'RETRIEVED','metrics':{'provider':'OpenAlex','h_index':4,'i10_index':2,'cited_by_count':20,'works_count':8}}],
            'publications':[{'source_key':'openalex:work:W123','title':'Relational collaboration discovery',
                'year':2025,'publication_date':'2025-06-01','doi':'https://doi.org/10.1000/TEST',
                'citations':3,'kind':'Journal','source_url':'https://api.openalex.org/works/W123','retrieved_at':captured,
                'venue':{'source_key':'openalex:source:S1','name':'Database Journal','kind':'journal'},
                'raw_authors':[{'name':'Alice','openalex_id':'https://openalex.org/A123'}]}],
            'authorships':[{'faculty_source_key':'vit:profile:1','publication_source_key':'openalex:work:W123','author_order':5,'identity_match_status':'VERIFIED'}]}
        raw=json.dumps(data).encode();(tmp_path/'enrichment.json').write_bytes(raw)
        manifest={'contract_version':2,'status':'complete','batch_id':'test_enrichment','files':{'enrichment.json':{'rows':1,'sha256':hashlib.sha256(raw).hexdigest()}}}
        (tmp_path/'manifest.json').write_text(json.dumps(manifest))
        first=load_enrichment(db,tmp_path);second=load_enrichment(db,tmp_path)
        assert first['counts']==second['counts']
        assert second['verified_provider_faculty']==1
        assert db.scalar(select(m.publication.c.doi).where(m.publication.c.source_key=='openalex:work:W123'))=='10.1000/test'
        metric=db.execute(select(m.faculty_metric_snapshot).where(m.faculty_metric_snapshot.c.faculty_id==ids[0])).mappings().one()
        assert (metric['provider'],metric['h_index'],metric['i10_index'])==('OpenAlex',4,2)
        assert db.scalar(select(m.faculty_publication.c.author_order).where(m.faculty_publication.c.faculty_id==ids[0],m.faculty_publication.c.author_order==5))==5
        data['authorships'][0]['faculty_source_key']='vit:profile:999'
        raw=json.dumps(data).encode();(tmp_path/'enrichment.json').write_bytes(raw)
        manifest['files']['enrichment.json']['sha256']=hashlib.sha256(raw).hexdigest()
        (tmp_path/'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValueError,match='reference'):load_enrichment(db,tmp_path)


def test_submission_sql_ddl_creates_the_same_model(postgres_database_factory):
    from sqlalchemy import inspect
    with postgres_database_factory() as uri:
        engine=create_engine(uri)
        raw=engine.raw_connection()
        try:
            with raw.cursor() as cursor:
                cursor.execute((ROOT/'docs/schema_postgresql.sql').read_text())
            raw.commit()
        finally:raw.close()
        assert set(inspect(engine).get_table_names())==set(m.metadata.tables)
        assert set(inspect(engine).get_view_names())=={'v_coauthor_edge','v_shared_research_area','v_faculty_discovery','v_lab_discovery'}
        engine.dispose()
