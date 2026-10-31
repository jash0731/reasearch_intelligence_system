#!/usr/bin/env python3
"""Initialize/load a separate PostgreSQL application database."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--enrichment',type=Path,action='append',default=[],help='Optional closed provider batch; may be repeated')
    args=parser.parse_args()
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError
    from research.database.loader import read_batch,load_directory,read_enrichment_batch,load_enrichment
    from research.database.sql import initialize_schema
    engine=None
    try:
        target=make_url(os.getenv('DATABASE_URL',''))
        if target.get_backend_name()!='postgresql' or not (target.database or '').endswith(('_app','_test')):
            raise ValueError('Only an explicit PostgreSQL database ending _app or _test is accepted; the live v1 database is refused')
        read_batch(args.batch)  # Validate before DDL or any row mutation.
        for enrichment in args.enrichment:read_enrichment_batch(enrichment)
        engine=create_engine(target.set(drivername='postgresql+psycopg'),pool_pre_ping=True)
        if args.initialize:initialize_schema(engine)
        with engine.begin() as connection:
            report=load_directory(connection,args.batch)
            enrichment_reports=[load_enrichment(connection,folder) for folder in args.enrichment]
            if enrichment_reports:
                report['counts']=enrichment_reports[-1]['counts']
                report['enrichment']=enrichment_reports
        output=json.dumps(report,indent=2)+'\n'
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(output)
        print(output,end='')
        return 0
    except ValueError as error:
        print('Import refused: '+str(error),file=sys.stderr);return 1
    except (KeyError,TypeError,OSError) as error:
        print('Import refused: incomplete or invalid batch ('+type(error).__name__+').',file=sys.stderr);return 1
    except SQLAlchemyError:
        print('PostgreSQL import failed; the data transaction was rolled back. Check connection and schema; no credentials were printed.',file=sys.stderr)
        return 1
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
