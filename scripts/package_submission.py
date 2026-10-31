#!/usr/bin/env python3
"""Create a reproducible, secret-free code-and-offline-data handover ZIP."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def package():
    files=set()
    for name in ['README.md','requirements.txt','requirements-dev.txt','pytest.ini','Dockerfile',
                 '.dockerignore','.env.example','.gitignore','compose.yaml','run.py',
                 'start_macos_linux.sh','start_windows.bat','THIRD_PARTY_NOTICES.md']:
        files.add(ROOT/name)
    # Explicit runtime/test entry points prevent retired modules returning to the ZIP.
    runtime = ['research/__init__.py', 'research/app.py', 'research/facilities_loader.py',
               'research/static/style.css', 'tests/conftest.py', 'tests/test_app.py',
               'tests/test_schema.py', 'tests/test_author_identity.py']
    files.update(ROOT/name for name in runtime)
    for folder, pattern in [('research/database', '*.py'), ('research/templates', '*.html')]:
        files.update((ROOT/folder).glob(pattern))
    scripts=['configure.py','start_workspace.py','init_databases.sql',
       'extract_directory.py','select_directory_candidates.py','finalize_directory.py',
       'extract_facilities.py','enrich_directory.py','build_directory_batch.py',
       'load_directory.py','package_submission.py']
    files.update(ROOT/'scripts'/name for name in scripts)
    docs=['PROJECT_REPORT.md','ER_AND_3NF.md','TEST_REPORT.md',
       'PUBLICATION_EXTRACTION.md','SCHEMA_VALIDATION.md',
       'schema_postgresql.sql','SQL_SHOWCASE.sql']
    files.update(ROOT/'docs'/name for name in docs)
    base=ROOT/'data/staging'
    pointer=base/'LATEST_ENRICHMENT'
    name=pointer.read_text().strip()
    if Path(name).name!=name or not name.startswith('batch_'):
        raise ValueError('Invalid snapshot pointer')
    files.add(pointer)
    for batch in ['batch_001_directory', name]:
        folder=base/batch
        manifest=json.loads((folder/'manifest.json').read_text())
        if manifest.get('status')!='complete' or manifest.get('contract_version')!=2:
            raise ValueError('A complete data batch is required')
        for filename,entry in manifest['files'].items():
            if Path(filename).name!=filename:raise ValueError('Invalid batch path')
            path=folder/filename
            if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('Snapshot checksum mismatch')
            files.add(path)
        files.update([folder/'manifest.json',folder/'quality_report.json'])
    files.add(ROOT/'data/staging/labs.json')
    forbidden={'.env','.DS_Store'}
    entries={}
    for path in sorted(files):
        if not path.is_file() or path.is_symlink():raise ValueError('Missing or symbolic submission file: '+str(path.relative_to(ROOT)))
        relative=str(path.relative_to(ROOT))
        if path.name in forbidden or any(part in {'raw','archive','cache','responses','.git'} for part in path.relative_to(ROOT).parts):
            raise ValueError('Forbidden submission content')
        entries[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    out=ROOT/'submission';out.mkdir(exist_ok=True)
    target=out/'VIT_Research_Connections_Submission.zip'
    temporary=target.with_suffix('.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):archive.write(path,'vit-research-intelligence/'+str(path.relative_to(ROOT)))
        archive.writestr('vit-research-intelligence/SUBMISSION_MANIFEST.json',json.dumps({
            'generated_at':datetime.now(timezone.utc).isoformat(),'files':entries},indent=2))
    temporary.replace(target)
    print(json.dumps({'zip':str(target),'files':len(entries),'bytes':target.stat().st_size,
                      'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__=='__main__':package()
