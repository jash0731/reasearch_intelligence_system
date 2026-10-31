FROM python:3.13-slim AS data_bundle
WORKDIR /source
COPY data/staging/ /source/staging/
# Include the directory batch and one closed enrichment batch.
RUN python - <<'PY'
import hashlib, json, pathlib, shutil
staging = pathlib.Path('/source/staging')
output = pathlib.Path('/bundle'); output.mkdir()
enrichment = (staging / 'LATEST_ENRICHMENT').read_text().strip()
assert pathlib.Path(enrichment).name == enrichment and enrichment.startswith('batch_'), 'Invalid enrichment pointer'
for batch_name in ['batch_001_directory', enrichment]:
    source = staging / batch_name
    manifest = json.loads((source / 'manifest.json').read_text())
    assert manifest.get('status') == 'complete' and manifest.get('contract_version') == 2
    target = output / batch_name; target.mkdir()
    for filename, info in manifest['files'].items():
        assert pathlib.Path(filename).name == filename
        raw = (source / filename).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == info['sha256']
        (target / filename).write_bytes(raw)
    for filename in ['manifest.json','quality_report.json']:
        shutil.copy2(source / filename,target / filename)
(output / 'LATEST_ENRICHMENT').write_text(enrichment + '\n')
shutil.copy2(staging / 'labs.json',output / 'labs.json')
PY

FROM python:3.13-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOST=0.0.0.0 APP_PORT=5000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY research/ ./research/
COPY scripts/start_workspace.py ./scripts/
COPY run.py ./
COPY --from=data_bundle /bundle/ ./data/staging/
RUN useradd --create-home demo && mkdir -p /app/instance && chown -R demo:demo /app
USER demo
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=4)" || exit 1
CMD ["python", "scripts/start_workspace.py"]

# Test dependencies live only in this explicit target.
FROM runtime AS test
USER root
COPY requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
COPY docs/schema_postgresql.sql docs/SQL_SHOWCASE.sql ./docs/
COPY scripts/enrich_directory.py ./scripts/
USER demo
CMD ["python", "-m", "pytest", "-q", "-W", "error"]
