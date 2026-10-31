#!/usr/bin/env python3
"""Offline, repeatable preparation and serving of the PostgreSQL workspace."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from werkzeug.security import generate_password_hash
    from research.database.sql import initialize_schema
    from research.database.loader import load_directory
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    raw = os.environ.get('DATABASE_URL', '')
    url = make_url(raw) if raw else None
    if not url or url.get_backend_name() != 'postgresql' or not (url.database or '').endswith('_app'):
        raise ValueError('Workspace preparation requires a separate PostgreSQL database ending _app; legacy database preserved.')
    password = os.environ.get('DEMO_PASSWORD', '')
    if len(password) < 12 or not os.environ.get('SECRET_KEY'):
        raise ValueError('Set SECRET_KEY and DEMO_PASSWORD (at least12characters). Use scripts/configure.py.')
    engine = create_engine(url.set(drivername='postgresql+psycopg'), pool_pre_ping=True)
    initialize_schema(engine)
    with engine.begin() as db:
        report = load_directory(db, ROOT / 'data/staging/batch_001_directory')
        labs = ROOT / 'data/staging/labs.json'
        if labs.exists():
            from research.facilities_loader import load_facilities
            report['facilities'] = load_facilities(db, labs)
    pointer = ROOT / 'data/staging/LATEST_ENRICHMENT'
    if pointer.exists():
        name = pointer.read_text().strip()
        if Path(name).name != name or not name.startswith('batch_'):
            raise ValueError('Invalid enrichment batch pointer')
        batch = ROOT / 'data/staging' / name
        from research.database.loader import load_enrichment
        with engine.begin() as db:
            report['enrichment'] = load_enrichment(db, batch)
    with engine.begin() as db:
        # Pick linked profiles with verified papers for useful offline demos.
        ids = list(db.execute(text('''SELECT f.id FROM faculty f
          LEFT JOIN faculty_publication a ON a.faculty_id=f.id GROUP BY f.id
          ORDER BY count(a.publication_id) DESC,f.name LIMIT 3''')).scalars())
        accounts = [('admin','ADMIN',None),('hod','HOD',ids[0]),
                    ('faculty_senior','FACULTY',ids[1]),('faculty_early','FACULTY',ids[2])]
        for username,role,fid in accounts:
            db.execute(text('''INSERT INTO user_account(username,password_hash,role,faculty_id)
              VALUES(:username,:password,:role,:fid) ON CONFLICT(username) DO NOTHING'''),
              {'username':username,'password':generate_password_hash(password),'role':role,'fid':fid})
    print(json.dumps(report, default=str), flush=True)
    engine.dispose()
    if args.prepare_only:
        return
    from research.app import create_app
    from waitress import serve
    app = create_app()
    print('PostgreSQL collaboration workspace ready on port5000. Credentials were not printed.', flush=True)
    serve(app, host=os.getenv('APP_HOST','127.0.0.1'), port=int(os.getenv('APP_PORT','5000')))


if __name__ == '__main__':
    main()
