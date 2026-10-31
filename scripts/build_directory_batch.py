#!/usr/bin/env python3
"""Close an offline directory-only batch; never publish or rewrite LATEST."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile


def build(source,destination):
    source=Path(source);destination=Path(destination)
    if destination.exists():raise ValueError('Batch already exists; choose a new immutable batch name')
    rows=json.loads(source.read_text())
    if not isinstance(rows,list) or not rows:raise ValueError('Expected nonempty directory candidate list')
    raw=(json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode()
    manifest={'contract_version':2,'status':'complete','batch_id':destination.name,
        'schema_version':2,'generated_at':datetime.now(timezone.utc).isoformat(),
        'scope':{'campus':'Vellore','schools':['SCOPE','SCORE'],'people':'faculty'},
        'collection_stage':'DIRECTORY_ONLY','files':{'faculty_directory.json':{
            'rows':len(rows),'sha256':hashlib.sha256(raw).hexdigest()}},
        'external_author_verification':'PENDING','publication_retrieval':'NOT_ATTEMPTED'}
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='.'+destination.name+'-',dir=destination.parent))
    try:
        (temporary/'faculty_directory.json').write_bytes(raw)
        (temporary/'quality_report.json').write_text(json.dumps({
            'faculty_candidates':len(rows),'by_school':{s:sum(r['profile_school_code']==s for r in rows) for s in ['SCOPE','SCORE']},
            'external_author_verification':'PENDING','publication_retrieval':'NOT_ATTEMPTED',
            'raw_mobile_numbers_included':False,'live_database_changed':False},indent=2)+'\n')
        # Manifest is last; directory rename makes the complete batch visible atomically.
        (temporary/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        temporary.rename(destination)
    finally:
        if temporary.exists():
            for file in temporary.iterdir():file.unlink()
            temporary.rmdir()
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=build(args.source,args.output)
    print('Closed directory batch:',result['batch_id'],'faculty:',result['files']['faculty_directory.json']['rows'])
