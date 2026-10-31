"""Load source-backed facilities without inferring faculty membership."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from .database import models as m
from .database.loader import upsert, normalized


def load_facilities(db, filename):
    payload = json.loads(Path(filename).read_text())
    if payload.get('status') != 'complete':
        raise ValueError('Facilities evidence batch is incomplete')
    for row in payload['labs']:
        if not row['url'].startswith('https://vit.ac.in/scope/facilities/'):
            raise ValueError('Only verified Vellore SCOPE source pages are accepted')
        school = db.scalar(select(m.school.c.id).where(m.school.c.code=='SCOPE'))
        source = upsert(db,m.source_record,{'source_key':'facility:'+row['sha256'],'source_type':'DIRECTORY',
          'url':row['url'],'retrieved_at':datetime.fromisoformat(row['retrieved_at']),
          'content_sha256':row['sha256'],'payload':row},['source_key'])
        lab = upsert(db,m.lab,{'source_key':row['url'],'name':row['name'],'school_id':school,
          'description':row['description'],'official_url':row['url'],'source_id':source},['source_key'])
        for term in row.get('areas',[]):
            area = upsert(db,m.research_area,{'name':term,'normalized_term':normalized(term)},['normalized_term'],preserve=['name'])
            upsert(db,m.lab_research_area,{'lab_id':lab,'area_id':area,'source_id':source,
              'assignment_method':'SOURCE_DECLARED'},['lab_id','area_id'])
    return {'facilities':len(payload['labs']),'memberships_inferred':0}
