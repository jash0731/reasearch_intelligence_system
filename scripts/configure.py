#!/usr/bin/env python3
"""Create private local Compose settings; never replace existing secrets."""
from pathlib import Path
import os
import secrets

root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
    print('.env already exists; no settings changed. Compose supplies the PostgreSQL connection.')
else:
    content=(root/'.env.example').read_text(encoding='utf-8')
    values={'SECRET_KEY':secrets.token_hex(32), 'POSTGRES_PASSWORD':secrets.token_hex(32),
            'DEMO_PASSWORD':secrets.token_urlsafe(18)}
    content='\n'.join(key+'='+values[key] if (key:=line.split('=',1)[0]) in values else line
                      for line in content.splitlines())+'\n'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:handle.write(content)
    print('Created private .env for PostgreSQL Compose. Demo login password is stored there. No secrets were printed.')
