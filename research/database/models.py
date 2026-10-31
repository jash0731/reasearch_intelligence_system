"""PostgreSQL relational model for selected Vellore SCOPE/SCORE faculty.

Core tables are explicit so their keys and constraints are inspectable. Raw JSON
is retained as source evidence, never as a replacement for operational joins.
"""
from sqlalchemy import (MetaData, Table, Column, Integer, Text, String, Boolean,
    Date, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Index, func)
from sqlalchemy.dialects.postgresql import JSONB

metadata=MetaData(naming_convention={
    'pk':'pk_%(table_name)s',
    'fk':'fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s',
    'uq':'uq_%(table_name)s_%(column_0_N_name)s',
    'ix':'ix_%(table_name)s_%(column_0_N_name)s',
})


def identity():
    return Column('id',Integer,primary_key=True)


def reference(name, target, *, nullable=False, primary_key=False, ondelete='RESTRICT'):
    return Column(name,Integer,ForeignKey(target,ondelete=ondelete),nullable=nullable,primary_key=primary_key)


def evidence():
    return reference('source_id','source_record.id')


source_record=Table('source_record',metadata,identity(),
    Column('source_key',Text,nullable=False,unique=True),
    Column('source_type',String(40),nullable=False),
    Column('url',Text,nullable=False),
    Column('retrieved_at',DateTime(timezone=True),nullable=False),
    Column('published_at',DateTime(timezone=True)),
    Column('report_month',String(7)),Column('content_sha256',String(64)),
    Column('cache_reference',Text),Column('payload',JSONB,nullable=False),
    CheckConstraint("source_type IN ('DIRECTORY','RESEARCH_PROFILE','EMAIL','PDF','API','MANUAL')",name='valid_source_type'))

school=Table('school',metadata,identity(),
    Column('code',String(10),nullable=False,unique=True),Column('name',Text,nullable=False),
    Column('campus',String(40),nullable=False,server_default='Vellore'),
    CheckConstraint("code IN ('SCOPE','SCORE')",name='supported_school'),
    CheckConstraint("campus='Vellore'",name='vellore_only'))

department=Table('department',metadata,identity(),reference('school_id','school.id'),
    Column('code',String(120),nullable=False),Column('name',Text,nullable=False),
    UniqueConstraint('school_id','code'),UniqueConstraint('school_id','name'))

faculty=Table('faculty',metadata,identity(),
    Column('source_key',Text,nullable=False,unique=True),
    Column('canonical_url',Text,nullable=False,unique=True),
    Column('name',Text,nullable=False),Column('designation',Text,nullable=False),
    Column('emp_id',String(40),unique=True),Column('email',Text),
    reference('department_id','department.id',nullable=True),evidence(),
    Column('publication_collection_status',String(30),nullable=False,server_default='NOT_ATTEMPTED'),
    CheckConstraint("publication_collection_status IN ('NOT_ATTEMPTED','IDENTITY_REVIEW','FETCH_FAILED','PARTIAL','RETRIEVED')",name='valid_collection_status'))

faculty_qualification=Table('faculty_qualification',metadata,identity(),
    reference('faculty_id','faculty.id',ondelete='CASCADE'),
    Column('source_key',Text,nullable=False,unique=True),Column('qualification',Text,nullable=False),
    Column('institution',Text),Column('specialization',Text),Column('graduation_year',Integer),
    Column('source_text',Text,nullable=False),evidence(),
    CheckConstraint('graduation_year BETWEEN 1900 AND 2100',name='valid_graduation_year'))

faculty_external_profile=Table('faculty_external_profile',metadata,identity(),
    reference('faculty_id','faculty.id',ondelete='CASCADE'),
    Column('provider',String(40),nullable=False),Column('external_id',Text,nullable=False),
    Column('url',Text,nullable=False),Column('identity_match_status',String(20),nullable=False,server_default='PENDING'),
    Column('checked_at',DateTime(timezone=True)),Column('resolution_evidence',Text),evidence(),
    UniqueConstraint('faculty_id','provider','external_id'),
    CheckConstraint("identity_match_status IN ('PENDING','VERIFIED','CONFLICT')",name='valid_identity_match_status'))
Index('uq_verified_external_identity',faculty_external_profile.c.provider,
      faculty_external_profile.c.external_id,unique=True,
      postgresql_where=faculty_external_profile.c.identity_match_status=='VERIFIED')

research_area=Table('research_area',metadata,identity(),Column('name',Text,nullable=False),
    Column('normalized_term',Text,nullable=False,unique=True))


def area_link(name, owner):
    table=Table(name,metadata,
        reference(owner+'_id',owner+'.id',primary_key=True,ondelete='CASCADE'),
        reference('area_id','research_area.id',primary_key=True),evidence(),
        Column('assignment_method',String(40),nullable=False),
        CheckConstraint("assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW','LITERAL_KEYWORD','AUTHOR_INTEREST_INFERRED')",name='valid_'+name+'_method'))
    Index('ix_'+name+'_area_owner',table.c.area_id,table.c[owner+'_id'])
    return table


faculty_research_area=area_link('faculty_research_area','faculty')

venue=Table('venue',metadata,identity(),Column('source_key',Text,nullable=False,unique=True),
    Column('name',Text,nullable=False),Column('kind',String(40)),Column('issn_l',String(30)),evidence())

publication=Table('publication',metadata,identity(),Column('source_key',Text,nullable=False,unique=True),
    Column('doi',Text,unique=True),Column('title',Text,nullable=False),Column('year',Integer),
    Column('publication_date',Date),Column('kind',String(40),nullable=False),
    reference('venue_id','venue.id',nullable=True),Column('abstract',Text),Column('raw_authors',Text),
    Column('citations',Integer),Column('citations_provider',String(100)),
    Column('citations_observed_at',DateTime(timezone=True)),evidence(),
    CheckConstraint('year BETWEEN 1900 AND 2100',name='valid_publication_year'),
    CheckConstraint('citations >= 0',name='nonnegative_publication_citations'))
Index('ix_publication_year',publication.c.year)

faculty_publication=Table('faculty_publication',metadata,
    reference('faculty_id','faculty.id',primary_key=True),
    reference('publication_id','publication.id',primary_key=True,ondelete='CASCADE'),
    Column('author_order',Integer),Column('is_corresponding',Boolean),
    Column('identity_match_status',String(20),nullable=False),evidence(),
    UniqueConstraint('publication_id','author_order'),
    CheckConstraint('author_order > 0',name='positive_author_order'),
    CheckConstraint("identity_match_status='VERIFIED'",name='verified_authorship_only'))
Index('ix_authorship_publication_faculty',faculty_publication.c.publication_id,faculty_publication.c.faculty_id)
publication_research_area=area_link('publication_research_area','publication')

lab=Table('lab',metadata,identity(),Column('source_key',Text,nullable=False,unique=True),
    Column('name',Text,nullable=False),reference('school_id','school.id',nullable=True),
    Column('description',Text),Column('official_url',Text),Column('contact_email',Text),evidence())
faculty_lab=Table('faculty_lab',metadata,
    reference('faculty_id','faculty.id',primary_key=True),
    reference('lab_id','lab.id',primary_key=True,ondelete='CASCADE'),
    Column('membership_role',Text),evidence())
lab_research_area=area_link('lab_research_area','lab')

project=Table('project',metadata,identity(),Column('source_key',Text,nullable=False,unique=True),
    Column('title',Text,nullable=False),Column('funder_name',Text),Column('kind',String(40)),
    Column('source_reported_status',String(40)),Column('status_as_of',Date),
    Column('start_date',Date),Column('end_date',Date),Column('official_url',Text),evidence())
faculty_project=Table('faculty_project',metadata,
    reference('faculty_id','faculty.id',primary_key=True),
    reference('project_id','project.id',primary_key=True,ondelete='CASCADE'),
    Column('participation_role',Text),evidence())
project_research_area=area_link('project_research_area','project')

faculty_metric_snapshot=Table('faculty_metric_snapshot',metadata,identity(),
    reference('faculty_id','faculty.id',ondelete='CASCADE'),
    Column('provider',String(120),nullable=False),Column('observed_at',DateTime(timezone=True),nullable=False),
    Column('metric_as_of',Date),Column('h_index',Integer),Column('i10_index',Integer),
    Column('cited_by_count',Integer),Column('works_count',Integer),evidence(),
    UniqueConstraint('faculty_id','provider','source_id'),
    CheckConstraint('h_index >= 0 AND i10_index >= 0 AND cited_by_count >= 0 AND works_count >= 0',name='nonnegative_author_metrics'))

patent=Table('patent',metadata,identity(),Column('source_key',Text,nullable=False,unique=True),
    Column('title',Text,nullable=False),Column('application_no',Text),Column('patent_no',Text),
    Column('status',String(20),nullable=False),Column('event_date',Date),Column('report_month',String(7)),evidence(),
    CheckConstraint("status IN ('FILED','PUBLISHED','GRANTED')",name='valid_patent_status'))
patent_inventor=Table('patent_inventor',metadata,
    reference('faculty_id','faculty.id',primary_key=True),
    reference('patent_id','patent.id',primary_key=True,ondelete='CASCADE'),
    Column('evidence_kind',String(40),nullable=False),evidence())

user_account=Table('user_account',metadata,identity(),Column('username',String(100),nullable=False,unique=True),
    Column('password_hash',Text,nullable=False),Column('role',String(20),nullable=False),
    Column('faculty_id',Integer,ForeignKey('faculty.id',ondelete='RESTRICT'),unique=True),
    CheckConstraint("role IN ('ADMIN','HOD','FACULTY')",name='faculty_only_user_roles'),
    CheckConstraint("faculty_id IS NOT NULL OR role='ADMIN'",name='linked_faculty_account'))

publication_audit=Table('publication_audit',metadata,identity(),
    Column('publication_id',Integer,nullable=False),Column('operation',String(10),nullable=False),
    Column('old_row',JSONB),Column('new_row',JSONB),
    Column('changed_at',DateTime(timezone=True),nullable=False,server_default=func.now()),
    CheckConstraint("operation IN ('INSERT','UPDATE','DELETE')",name='valid_audit_operation'))

assert len(metadata.tables)==23
