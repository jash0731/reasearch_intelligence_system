"""Validated, offline and transactional import of a closed directory batch."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs,urlparse

from sqlalchemy import select,delete,func
from sqlalchemy.dialects.postgresql import insert
from . import models as m

SCHOOLS={
 'SCOPE':'School of Computer Science and Engineering',
 'SCORE':'School of Computer Science Engineering and Information Systems',
}


def normalized(value):
    return re.sub(r'\s+',' ',value.strip()).casefold()


def stable(*values):
    return hashlib.sha256(json.dumps(values,ensure_ascii=False).encode()).hexdigest()


def read_batch(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('contract_version')!=2 or manifest.get('status')!='complete':
        raise ValueError('A complete contract-version-2 manifest is required')
    if set(manifest.get('files',{}))!={'faculty_directory.json'}:
        raise ValueError('Unexpected directory batch files')
    raw=(folder/'faculty_directory.json').read_bytes();info=manifest['files']['faculty_directory.json']
    if hashlib.sha256(raw).hexdigest()!=info.get('sha256'):
        raise ValueError('Directory checksum mismatch')
    rows=json.loads(raw)
    if not isinstance(rows,list) or len(rows)!=info.get('rows') or not rows:
        raise ValueError('Invalid directory row count')
    seen=set()
    for row in rows:
        url=row.get('canonical_url','')
        if not re.fullmatch(r'https://vitdirectory\.vit\.ac\.in/page/faculty/\d+',url) or url in seen:
            raise ValueError('Canonical profile identity is invalid or duplicated')
        seen.add(url)
        if row.get('status')!='EXTRACTED' or row.get('profile_school_code') not in SCHOOLS:
            raise ValueError('Faculty must have an extracted SCOPE/SCORE official profile')
        if row.get('review_reasons') or row.get('external_identity_verification')!='PENDING':
            raise ValueError('Directory batch must not promote unresolved conflicts or claim verified external identities')
        for field in ['name','designation','department','qualifications','research_interests']:
            if not row.get(field):raise ValueError('Missing required directory field: '+field)
        if not any(key in row.get('external_profiles',{}) for key in ['orcid','google_scholar']):
            raise ValueError('Missing external profile link')
        if row.get('publication_collection_status')!='NOT_ATTEMPTED':
            raise ValueError('Directory-only batch cannot claim publication retrieval')
        source=row.get('source',{})
        captured_at=datetime.fromisoformat(source['retrieved_at'])
        if captured_at.tzinfo is None:
            raise ValueError('Source retrieval time must include a timezone')
        if not re.fullmatch(r'[0-9a-f]{64}',source.get('sha256','')):
            raise ValueError('Missing source content checksum')
        if not any(o.get('campus')=='Vellore' and o.get('school_code')==row['profile_school_code'] for o in row.get('roster_observations',[])):
            raise ValueError('Missing Vellore school roster evidence')
    return manifest,rows


def upsert(db,table,values,keys,preserve=()):
    statement=insert(table).values(**values)
    updates={k:getattr(statement.excluded,k) for k in values if k not in {*keys,*preserve}}
    statement=(statement.on_conflict_do_update(index_elements=keys,set_=updates) if updates else
               statement.on_conflict_do_nothing(index_elements=keys))
    if 'id' in table.c:
        found=db.execute(statement.returning(table.c.id)).scalar_one_or_none()
        return found if found is not None else db.scalar(select(table.c.id).where(*(table.c[k]==values[k] for k in keys)))
    db.execute(statement)


def external_identity(provider,url):
    parsed=urlparse(url)
    if parsed.scheme!='https':raise ValueError('Research links must use HTTPS')
    if provider=='google_scholar':return parse_qs(parsed.query)['user'][0]
    if provider=='scopus':return parse_qs(parsed.query)['authorId'][0]
    if provider in {'orcid','openalex'}:return parsed.path.rstrip('/').rsplit('/',1)[-1]
    return url


def load_directory(db,folder):
    """Caller supplies a transaction; validation failure must leave it uncommitted."""
    manifest,rows=read_batch(folder)
    school_ids={code:upsert(db,m.school,{'code':code,'name':name,'campus':'Vellore'},['code']) for code,name in SCHOOLS.items()}
    for row in rows:
        url=row['canonical_url'];captured=row['source'];observed=datetime.fromisoformat(captured['retrieved_at'])
        source=upsert(db,m.source_record,{
            'source_key':'directory:'+stable(url,captured['sha256']),
            'source_type':'DIRECTORY','url':url,'retrieved_at':observed,
            'content_sha256':captured['sha256'],'payload':row},['source_key'])
        department_id=upsert(db,m.department,{'school_id':school_ids[row['profile_school_code']],
            'name':row['department'],'code':re.sub(r'[^a-z0-9]+','-',row['department'].casefold()).strip('-')},['school_id','code'])
        emails=row.get('institutional_emails',[])
        faculty_id=upsert(db,m.faculty,{'source_key':'vit:profile:'+url.rsplit('/',1)[-1],
            'canonical_url':url,'name':row['name'],'designation':row['designation'],
            'email':emails[0] if emails else None,'department_id':department_id,'source_id':source,
            'publication_collection_status':'NOT_ATTEMPTED'},['source_key'],preserve=['publication_collection_status'])
        db.execute(delete(m.faculty_qualification).where(m.faculty_qualification.c.faculty_id==faculty_id))
        for qualification in row['qualifications']:
            text=qualification['source_text'];year=re.search(r'Graduated in\s+(\d{4})',text)
            upsert(db,m.faculty_qualification,{'faculty_id':faculty_id,
                'source_key':'qualification:'+stable(url,text),'qualification':qualification['qualification'],
                'institution':qualification.get('institution'),'specialization':qualification.get('specialization'),
                'graduation_year':int(year[1]) if year else None,'source_text':text,'source_id':source},['source_key'])
        for provider,profile in row['external_profiles'].items():
            profiles=profile if isinstance(profile,list) else [profile]
            for item in profiles:
                link=item['url'];identity=external_identity(provider,link)
                upsert(db,m.faculty_external_profile,{'faculty_id':faculty_id,'provider':provider,
                    'external_id':identity,'url':link,'identity_match_status':'PENDING','source_id':source},
                    ['faculty_id','provider','external_id'],preserve=['identity_match_status'])
        db.execute(delete(m.faculty_research_area).where(m.faculty_research_area.c.faculty_id==faculty_id))
        for term in row['research_interests']:
            area_id=upsert(db,m.research_area,{'name':term.strip(),'normalized_term':normalized(term)},['normalized_term'],preserve=['name'])
            upsert(db,m.faculty_research_area,{'faculty_id':faculty_id,'area_id':area_id,'source_id':source,
                'assignment_method':'SOURCE_DECLARED'},['faculty_id','area_id'])
        metric=row.get('source_reported_metrics',{})
        if metric:
            values={key:metric[key]['value'] for key in ['h_index','i10_index'] if key in metric}
            upsert(db,m.faculty_metric_snapshot,{'faculty_id':faculty_id,
                'provider':'VIT faculty profile; underlying provider unspecified','observed_at':observed,
                'source_id':source,**values},['faculty_id','provider','source_id'])
        for item in row.get('contributions',[]):
            section=item['section'];values=item['values'];headers=item['headers']
            if not values or values[0].strip().casefold() in {'-','nil','none','n/a'}:continue
            fields={normalized(h):v for h,v in zip(headers,values)}
            title=values[0];key='directory-contribution:'+stable(url,section,values)
            if 'project' in section and ('funded' in section or 'consultancy' in section):
                project_id=upsert(db,m.project,{'source_key':key,'title':title,
                    'funder_name':fields.get('funding agency'),'kind':'CONSULTANCY' if 'consultancy' in section else 'FUNDED',
                    'source_reported_status':'COMPLETED' if section.startswith('completed') else 'ONGOING' if section.startswith(('ongoing','on-going')) else None,
                    'status_as_of':None,'official_url':url,'source_id':source},['source_key'])
                upsert(db,m.faculty_project,{'faculty_id':faculty_id,'project_id':project_id,
                    'participation_role':None,'source_id':source},['faculty_id','project_id'])
            elif section.startswith('patent-'):
                status='PUBLISHED' if 'published' in section else 'GRANTED' if 'granted' in section else 'FILED' if 'filed' in section else None
                if not status:continue
                patent_id=upsert(db,m.patent,{'source_key':key,'title':title,'status':status,
                    'application_no':fields.get('application no.'),'patent_no':fields.get('patent no.'),
                    'source_id':source},['source_key'])
                upsert(db,m.patent_inventor,{'faculty_id':faculty_id,'patent_id':patent_id,
                    'evidence_kind':'LISTED_ON_OFFICIAL_PROFILE','source_id':source},['faculty_id','patent_id'])
    counts={name:db.scalar(select(func.count()).select_from(table)) for name,table in m.metadata.tables.items()}
    states=dict(db.execute(select(m.faculty.c.publication_collection_status,func.count()).group_by(m.faculty.c.publication_collection_status)).all())
    identity_states=dict(db.execute(select(m.faculty_external_profile.c.identity_match_status,func.count()).group_by(m.faculty_external_profile.c.identity_match_status)).all())
    return {'batch_id':manifest['batch_id'],'counts':counts,
        'publication_collection_states':states,'external_identity_states':identity_states,
        'labs':'No verified lab records supplied; none inferred',
        'other_contributions':'Books/chapters and other profile tables retained in source payload; not asserted as verified authorships'}


def read_enrichment_batch(folder):
    """Validate a closed provider batch before opening the import transaction."""
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('contract_version')!=2 or manifest.get('status')!='complete':
        raise ValueError('A complete contract-version-2 enrichment manifest is required')
    if set(manifest.get('files',{}))!={'enrichment.json'}:
        raise ValueError('Unexpected enrichment batch files')
    raw=(folder/'enrichment.json').read_bytes()
    info=manifest['files']['enrichment.json']
    if hashlib.sha256(raw).hexdigest()!=info.get('sha256'):
        raise ValueError('Enrichment checksum mismatch')
    data=json.loads(raw)
    for key in ('faculty','publications','authorships'):
        if not isinstance(data.get(key),list):raise ValueError('Missing enrichment list: '+key)
    if len(data['publications'])!=info.get('rows'):
        raise ValueError('Enrichment publication count mismatch')
    faculty_keys=set();work_keys=set()
    for row in data['faculty']:
        key=row.get('source_key','')
        if not re.fullmatch(r'vit:profile:\d+',key) or key in faculty_keys:
            raise ValueError('Invalid or repeated enrichment faculty key')
        faculty_keys.add(key)
        if row.get('publication_collection_status') not in {'RETRIEVED','PARTIAL','FETCH_FAILED','IDENTITY_REVIEW'}:
            raise ValueError('Invalid publication collection status')
        if row.get('openalex_id') and not row.get('identity_evidence'):
            raise ValueError('Verified provider identity requires matching evidence')
    for row in data['publications']:
        key=row.get('source_key','')
        if not re.fullmatch(r'openalex:work:W\d+',key) or key in work_keys or not row.get('title'):
            raise ValueError('Invalid or repeated provider work')
        work_keys.add(key)
    links=set()
    verified_keys={r['source_key'] for r in data['faculty'] if r.get('openalex_id') and r.get('identity_evidence')}
    for row in data['authorships']:
        key=(row.get('faculty_source_key'),row.get('publication_source_key'))
        if key in links or key[0] not in verified_keys or key[1] not in work_keys:
            raise ValueError('Invalid or repeated verified authorship reference')
        links.add(key)
        if row.get('identity_match_status')!='VERIFIED':
            raise ValueError('Only verified authorships can be imported')
        order=row.get('author_order')
        if order is not None and (not isinstance(order,int) or isinstance(order,bool) or order<=0):
            raise ValueError('Original author order must be positive or unknown')
    return manifest,data


def load_enrichment(db,folder):
    """Load independently verified OpenAlex identities and work relationships.

    The caller must enclose this operation in a transaction. Identity evidence is
    retained with the captured author response; directory links are not treated
    as sufficient proof. Provider metrics describe the provider corpus, while
    loaded publications cover the declared collection window.
    """
    manifest,data=read_enrichment_batch(folder)
    faculty_ids=dict(db.execute(select(m.faculty.c.source_key,m.faculty.c.id)).all())
    if any(row['source_key'] not in faculty_ids for row in data['faculty']):
        raise ValueError('Enrichment refers to a faculty identity outside the curated directory')
    source_ids={};work_ids={}
    imported_faculty={row['source_key'] for row in data['faculty']}
    for review in data.get('review',[]):
        key=review.get('faculty_source_key')
        if key in faculty_ids and key not in imported_faculty:
            state='FETCH_FAILED' if review.get('reason')=='NO_CACHED_RESPONSE' else 'IDENTITY_REVIEW'
            db.execute(m.faculty.update().where(m.faculty.c.id==faculty_ids[key]).values(publication_collection_status=state))

    def source(row,kind='API'):
        captured=row.get('retrieved_at') or row.get('citations_observed_at') or row.get('observed_at')
        observed=datetime.fromisoformat(captured)
        if observed.tzinfo is None:raise ValueError('Provider retrieval time must include a timezone')
        raw=json.dumps(row,ensure_ascii=False,sort_keys=True).encode()
        checksum=hashlib.sha256(raw).hexdigest()
        url=row.get('source_url') or row.get('openalex_id')
        if not url or not url.startswith('https://'):raise ValueError('Provider evidence needs an HTTPS source URL')
        return upsert(db,m.source_record,{'source_key':'openalex:'+stable(url,checksum),
            'source_type':kind,'url':url,'retrieved_at':observed,'content_sha256':checksum,'payload':row},['source_key'])

    for row in data['faculty']:
        faculty_id=faculty_ids[row['source_key']]
        db.execute(m.faculty.update().where(m.faculty.c.id==faculty_id).values(publication_collection_status=row['publication_collection_status']))
        if not row.get('openalex_id'):continue
        observed=datetime.fromisoformat(row['retrieved_at'])
        source_id=source(row)
        evidence=json.dumps(row['identity_evidence'],ensure_ascii=False,sort_keys=True)
        author_id=row['openalex_id'].rstrip('/').rsplit('/',1)[-1]
        if not re.fullmatch(r'A\d+',author_id):raise ValueError('Invalid OpenAlex author identifier')
        upsert(db,m.faculty_external_profile,{'faculty_id':faculty_id,'provider':'openalex','external_id':author_id,
            'url':'https://openalex.org/'+author_id,'identity_match_status':'VERIFIED','checked_at':observed,
            'resolution_evidence':evidence,'source_id':source_id},['faculty_id','provider','external_id'])
        if row.get('external_orcid'):
            orcid=row['external_orcid'].rstrip('/').rsplit('/',1)[-1]
            # Only promote the exact official claim checked by the collector.
            db.execute(m.faculty_external_profile.update().where(
                m.faculty_external_profile.c.faculty_id==faculty_id,
                m.faculty_external_profile.c.provider=='orcid',m.faculty_external_profile.c.external_id==orcid
            ).values(identity_match_status='VERIFIED',checked_at=observed,resolution_evidence=evidence))
        metric=row.get('metrics') or {}
        if metric:
            if metric.get('provider')!='OpenAlex':raise ValueError('Unexpected metric provider')
            fields={key:metric.get(key) for key in ('h_index','i10_index','cited_by_count','works_count')}
            upsert(db,m.faculty_metric_snapshot,{'faculty_id':faculty_id,'provider':'OpenAlex',
                'observed_at':datetime.fromisoformat(metric.get('observed_at') or row['retrieved_at']),
                'source_id':source_id,**fields},['faculty_id','provider','source_id'])
    for row in data['publications']:
        source_id=source(row)
        venue=row.get('venue');venue_id=None
        if venue and venue.get('name'):
            venue_id=upsert(db,m.venue,{'source_key':venue['source_key'],'name':venue['name'],
                'kind':venue.get('kind'),'issn_l':venue.get('issn_l'),'source_id':source_id},['source_key'])
        doi=row.get('doi')
        if doi:
            doi=re.sub(r'^https?://(?:dx\.)?doi\.org/','',doi.strip(),flags=re.I).casefold()
        fields={'source_key':row['source_key'],'doi':doi or None,'title':row['title'],'year':row.get('year'),
            'publication_date':datetime.fromisoformat(row['publication_date']).date() if row.get('publication_date') else None,
            'kind':row.get('kind') or 'Other','venue_id':venue_id,'abstract':row.get('abstract'),
            'raw_authors':json.dumps(row.get('raw_authors',[]),ensure_ascii=False),
            'citations':row.get('citations'),'citations_provider':row.get('citations_provider') or 'OpenAlex',
            'citations_observed_at':datetime.fromisoformat(row.get('citations_observed_at') or row['retrieved_at']),
            'source_id':source_id}
        existing=db.scalar(select(m.publication.c.id).where(m.publication.c.source_key==row['source_key']))
        if existing is None and doi:existing=db.scalar(select(m.publication.c.id).where(m.publication.c.doi==doi))
        if existing is None:work_id=upsert(db,m.publication,fields,['source_key'])
        else:
            fields.pop('source_key')
            current=db.execute(select(m.publication).where(m.publication.c.id==existing)).mappings().one()
            if any(current[key]!=value for key,value in fields.items()):
                db.execute(m.publication.update().where(m.publication.c.id==existing).values(**fields))
            work_id=existing
        work_ids[row['source_key']]=work_id;source_ids[row['source_key']]=source_id
    for row in data['authorships']:
        upsert(db,m.faculty_publication,{'faculty_id':faculty_ids[row['faculty_source_key']],
            'publication_id':work_ids[row['publication_source_key']],'author_order':row.get('author_order'),
            'is_corresponding':row.get('is_corresponding'),'identity_match_status':'VERIFIED',
            'source_id':source_ids[row['publication_source_key']]},['faculty_id','publication_id'])
    return {'batch_id':manifest['batch_id'],'counts':{
        name:db.scalar(select(func.count()).select_from(table)) for name,table in m.metadata.tables.items()},
        'verified_provider_faculty':sum(bool(r.get('openalex_id')) for r in data['faculty']),
        'review_count':len(data.get('review',[])),
        'collection_window':data.get('collection_window','2019 onward; provider corpus may be incomplete')}
