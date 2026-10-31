"""Collaboration workspace backed exclusively by PostgreSQL application schema.

Discovery uses exact declared-area joins, literal title filtering and witnessed
coauthorship paths. No metric or inferred similarity determines a match.
"""
import hmac
import os
import secrets
from collections import defaultdict
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .database.sql import TWO_HOP_PATHS


def literal_pattern(value):
    """Build a substring pattern while treating SQL wildcard input literally."""
    return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def group_project_reports(reports, keyword=''):
    """Group title matches for display without merging their source observations."""
    groups = {}
    for report in reports:
        title = ' '.join(report['title'].split())
        key = title.casefold()
        if key.strip(' -–—.') in {'', 'n/a', 'na', 'nil', 'none', 'not applicable'}:
            continue
        group = groups.setdefault(key, {'title': title, 'reports': []})
        group['reports'].append(report)
    term = keyword.casefold()
    result = []
    for key, group in sorted(groups.items()):
        group['reports'].sort(key=lambda r: ((r.get('faculty_names') or '').casefold(), r['id']))
        searchable = ' '.join(str(r.get(field) or '') for r in group['reports']
                              for field in ('title', 'faculty_names', 'funder_name'))
        if not term or term in searchable.casefold():
            result.append(group)
    return result


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY'), DATABASE_URL=os.getenv('DATABASE_URL', ''),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true')
    app.config.update(config or {})
    uri = app.config['DATABASE_URL']
    if not uri.startswith(('postgresql://', 'postgresql+psycopg://')):
        raise ValueError('PostgreSQL DATABASE_URL is required')
    if not app.config['SECRET_KEY']:
        raise ValueError('SECRET_KEY is required')
    engine = create_engine(uri.replace('postgresql://', 'postgresql+psycopg://', 1), pool_pre_ping=True)
    app.extensions['engine'] = engine

    def rows(sql, **params):
        with engine.connect() as db:
            return [dict(r) for r in db.execute(text(sql), params).mappings()]

    def one(sql, **params):
        result = rows(sql, **params)
        return result[0] if result else None

    def faculty_rows():
        result = rows("SELECT *,canonical_url AS profile_url,canonical_url AS official_url FROM v_faculty_discovery d WHERE publication_collection_status IN ('PARTIAL','RETRIEVED') AND EXISTS(SELECT 1 FROM faculty_publication a WHERE a.faculty_id=d.faculty_id) ORDER BY name,faculty_id")
        interests = defaultdict(list)
        for area in rows('SELECT a.faculty_id,r.name FROM faculty_research_area a JOIN research_area r ON r.id=a.area_id ORDER BY r.name'):
            interests[area['faculty_id']].append(area['name'])
        for person in result:
            person['id'] = person['faculty_id']
            person['interests'] = interests[person['id']]
        return result

    def person(fid):
        record = one("SELECT *,canonical_url AS profile_url,canonical_url AS official_url FROM v_faculty_discovery d WHERE faculty_id=:id AND publication_collection_status IN ('PARTIAL','RETRIEVED') AND EXISTS(SELECT 1 FROM faculty_publication a WHERE a.faculty_id=d.faculty_id)", id=fid)
        if record:
            record['id'] = record['faculty_id']
        return record

    def papers_for(fid):
        return rows('''SELECT p.*,v.name AS venue_name,COALESCE('https://doi.org/'||p.doi,s.url) AS url
          FROM faculty_publication a JOIN publication p ON p.id=a.publication_id
          LEFT JOIN venue v ON v.id=p.venue_id JOIN source_record s ON s.id=p.source_id
          WHERE a.faculty_id=:id ORDER BY p.year DESC NULLS LAST,p.title''', id=fid)

    def matching_papers(keyword):
        return rows("""SELECT a.faculty_id,p.id,p.title,p.year,
          COALESCE('https://doi.org/'||p.doi,s.url) AS url
          FROM faculty_publication a JOIN publication p ON p.id=a.publication_id
          JOIN source_record s ON s.id=p.source_id
          WHERE p.title ILIKE :term ESCAPE '\\'
          ORDER BY p.year DESC NULLS LAST,p.title""", term=literal_pattern(keyword))

    def csrf():
        if not hmac.compare_digest(str(session.get('csrf_token', '')), request.form.get('csrf_token', '')) or not session.get('csrf_token'):
            abort(400, 'The form expired. Reload the page and try again.')

    @app.before_request
    def request_context():
        session.setdefault('csrf_token', secrets.token_urlsafe(32))

    @app.context_processor
    def common():
        user = one('SELECT id,username,role,faculty_id FROM user_account WHERE id=:id', id=session['user_id']) if session.get('user_id') else None
        return {'current_user': user, 'csrf_token': session['csrf_token']}

    @app.get('/')
    def home():
        return redirect(url_for('collaborators'))

    @app.get('/health')
    def health():
        one('SELECT 1 AS ok')
        return {'status': 'ok', 'schema': 2, 'database': 'PostgreSQL'}

    @app.get('/network')
    def network():
        return redirect(url_for('collaborators', **{k: v for k, v in request.args.items() if k in {'faculty_id', 'q', 'school', 'department', 'connection'}}))

    @app.get('/collaborators')
    def collaborators():
        faculty = faculty_rows()
        fid = request.args.get('faculty_id', type=int)
        # An omitted selection uses the account default; an empty selection stays empty.
        if 'faculty_id' not in request.args and session.get('user_id'):
            account = one('SELECT faculty_id FROM user_account WHERE id=:id', id=session['user_id'])
            fid = account['faculty_id'] if account else None
        selected = next((f for f in faculty if f['id'] == fid), None)
        if fid and not selected:
            abort(404)
        filters = {'faculty_id': fid, 'q': request.args.get('q', '').strip()[:150],
                   'school': request.args.get('school', ''), 'department': request.args.get('department', ''),
                   'connection': request.args.get('connection', 'all') if selected else 'all'}
        suggestions = []
        if selected:
            shared = defaultdict(list)
            for r in rows('''SELECT b.faculty_id,r.name FROM faculty_research_area a
              JOIN faculty_research_area b ON b.area_id=a.area_id AND b.faculty_id<>a.faculty_id
              JOIN research_area r ON r.id=a.area_id WHERE a.faculty_id=:id
              AND a.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
              AND b.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW') ORDER BY r.name''', id=fid):
                shared[r['faculty_id']].append(r['name'])
            direct = defaultdict(list)
            for r in rows('''SELECT b.faculty_id,p.id,p.title,p.year,COALESCE('https://doi.org/'||p.doi,s.url) AS url
              FROM faculty_publication a JOIN faculty_publication b ON b.publication_id=a.publication_id AND b.faculty_id<>a.faculty_id
              JOIN publication p ON p.id=a.publication_id JOIN source_record s ON s.id=p.source_id
              WHERE a.faculty_id=:id ORDER BY p.year DESC NULLS LAST,p.title''', id=fid):
                direct[r.pop('faculty_id')].append(r)
            paths = defaultdict(list)
            witnesses = rows(TWO_HOP_PATHS, faculty_id=fid)
            by_id = {f['id']: f for f in faculty}
            pub_ids = {r[k] for r in witnesses for k in ('first_publication_id', 'second_publication_id')}
            pubmap = {r['id']: r for r in rows("SELECT p.id,p.title,p.year,COALESCE('https://doi.org/'||p.doi,s.url) AS url FROM publication p JOIN source_record s ON s.id=p.source_id WHERE p.id=ANY(:ids)", ids=list(pub_ids))} if pub_ids else {}
            seen = set()
            for r in witnesses:
                key = r['candidate_id'], r['intermediary_id']
                if key in seen:
                    continue
                seen.add(key)
                if r['intermediary_id'] not in by_id:
                    continue
                intermediary = by_id[r['intermediary_id']]
                paths[r['candidate_id']].append({'id': intermediary['id'], 'name': intermediary['name'],
                    'first_paper': pubmap[r['first_publication_id']], 'second_paper': pubmap[r['second_publication_id']]})
            keyword = defaultdict(list)
            if filters['q']:
                for r in matching_papers(filters['q']):
                    keyword[r.pop('faculty_id')].append(r)
            candidate_ids = set(keyword) if filters['q'] else set(shared) | set(direct) | set(paths)
            for candidate_id in candidate_ids - {fid}:
                if candidate_id not in by_id:
                    continue
                item = dict(by_id[candidate_id])
                distance = 1 if direct[candidate_id] else 2 if paths[candidate_id] else None
                if filters['school'] and item['school_code'] != filters['school']:
                    continue
                if filters['department'] and str(item['department_id']) != filters['department']:
                    continue
                if filters['connection'] == 'direct' and distance != 1:
                    continue
                if filters['connection'] == 'two-hop' and distance != 2:
                    continue
                if filters['connection'] == 'new' and distance == 1:
                    continue
                item.update(shared_areas=shared[candidate_id], shared_papers=direct[candidate_id],
                            intermediaries=paths[candidate_id][:3], distance=distance,
                            keyword_evidence=keyword[candidate_id][:3])
                suggestions.append(item)
            suggestions.sort(key=lambda f: (-len(f['shared_areas']), f['distance'] or 3, f['name']))
        elif filters['q']:
            found = matching_papers(filters['q'])
            evidence = defaultdict(list)
            for r in found:
                evidence[r.pop('faculty_id')].append(r)
            for f in faculty:
                if f['id'] not in evidence or (filters['school'] and filters['school'] != f['school_code']):
                    continue
                if filters['department'] and filters['department'] != str(f['department_id']):
                    continue
                item = dict(f)
                item.update(shared_areas=[],shared_papers=[],intermediaries=[],distance=None,keyword_evidence=evidence[f['id']][:3])
                suggestions.append(item)
        schools = rows('SELECT code,name FROM school ORDER BY code')
        departments = rows('SELECT d.id,d.name,s.code AS school_code FROM department d JOIN school s ON s.id=d.school_id ORDER BY s.code,d.name')
        lab_suggestions = []
        if selected:
            lab_suggestions = rows("""SELECT l.id,l.name,l.description,l.official_url,array_agg(DISTINCT r.name ORDER BY r.name) AS matching_areas
              FROM faculty_research_area f JOIN lab_research_area a ON a.area_id=f.area_id
              JOIN lab l ON l.id=a.lab_id JOIN research_area r ON r.id=a.area_id
              WHERE f.faculty_id=:id AND f.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW')
              AND a.assignment_method IN ('SOURCE_DECLARED','MANUAL_REVIEW') GROUP BY l.id ORDER BY l.name""",id=fid)
        if filters['q']:
            lab_suggestions = rows("""SELECT id,name,description,official_url FROM lab
              WHERE name ILIKE :term ESCAPE '\\' OR description ILIKE :term ESCAPE '\\' ORDER BY name""",term=literal_pattern(filters['q']))
            for lab in lab_suggestions:
                lab['matched_keyword'] = filters['q']
        return render_template('collaborators.html', faculty=faculty, selected_faculty=selected, lab_suggestions=lab_suggestions,
            suggestions=suggestions, schools=schools, departments=departments, filters=filters)

    @app.get('/faculty')
    def directory():
        q = request.args.get('q', '').strip().casefold()
        school = request.args.get('school', '')
        department = request.args.get('department','')
        records = [f for f in faculty_rows() if (not q or q in f['name'].casefold() or q in (f['department_name'] or '').casefold() or any(q in a.casefold() for a in f['interests'])) and (not school or school==f['school_code']) and (not department or department==str(f['department_id']))]
        return render_template('directory.html', faculty=records, q=request.args.get('q',''), school=school,
                               schools=rows('SELECT code,name FROM school ORDER BY code'), total=len(records),
                               departments=rows('SELECT id,name FROM department ORDER BY name'),filters={'q':q,'school':school,'department':department})

    @app.get('/faculty/<int:faculty_id>')
    def faculty_profile(faculty_id):
        f = person(faculty_id)
        if not f:
            abort(404)
        return render_template('profile.html', faculty=f,
            qualifications=rows('SELECT * FROM faculty_qualification WHERE faculty_id=:id ORDER BY id', id=faculty_id),
            areas=rows('SELECT r.name FROM research_area r JOIN faculty_research_area a ON a.area_id=r.id WHERE a.faculty_id=:id ORDER BY r.name', id=faculty_id),
            external_profiles=rows('SELECT * FROM faculty_external_profile WHERE faculty_id=:id ORDER BY provider', id=faculty_id),
            metrics=rows('SELECT m.*,s.url AS source_url FROM faculty_metric_snapshot m JOIN source_record s ON s.id=m.source_id WHERE m.faculty_id=:id ORDER BY observed_at DESC,provider', id=faculty_id),
            papers=papers_for(faculty_id),
            projects=rows('SELECT p.*,s.url AS source_url FROM project p JOIN faculty_project a ON a.project_id=p.id JOIN source_record s ON s.id=p.source_id WHERE a.faculty_id=:id ORDER BY p.title', id=faculty_id),
            patents=rows('SELECT p.*,s.url AS source_url FROM patent p JOIN patent_inventor a ON a.patent_id=p.id JOIN source_record s ON s.id=p.source_id WHERE a.faculty_id=:id ORDER BY p.title', id=faculty_id))

    @app.get('/publications')
    def publications():
        q = request.args.get('q', '').strip()[:150]
        page = max(request.args.get('page', 1, type=int), 1)
        papers = rows('''SELECT p.*,v.name AS venue_name,COALESCE('https://doi.org/'||p.doi,s.url) AS url,
          (SELECT string_agg(f.name,', ' ORDER BY a.author_order) FROM faculty_publication a
           JOIN faculty f ON f.id=a.faculty_id WHERE a.publication_id=p.id) AS faculty_names
          FROM publication p LEFT JOIN venue v ON v.id=p.venue_id JOIN source_record s ON s.id=p.source_id
          WHERE p.title ILIKE :q ESCAPE '\\' ORDER BY p.year DESC NULLS LAST,p.title,p.id LIMIT 51 OFFSET :offset''', q=literal_pattern(q), offset=(page-1)*50)
        return render_template('publications.html', papers=papers[:50], q=q, page=page, has_next=len(papers)>50)

    @app.get('/<any(labs,projects):kind>')
    def entities(kind):
        q = request.args.get('q','').strip()
        if kind == 'labs':
            items = rows('SELECT l.*,s.url AS source_url FROM lab l JOIN source_record s ON s.id=l.source_id ORDER BY l.name')
            for item in items:
                item['areas'] = rows('SELECT r.name FROM research_area r JOIN lab_research_area a ON a.area_id=r.id WHERE a.lab_id=:id ORDER BY r.name',id=item['id'])
            if q:
                items = [i for i in items if q.casefold() in ' '.join(str(i.get(k) or '') for k in ['name','description']).casefold()]
        else:
            items = rows('''SELECT p.*,s.url AS source_url,(SELECT string_agg(f.name,', ' ORDER BY f.name)
              FROM faculty_project a JOIN faculty f ON f.id=a.faculty_id WHERE a.project_id=p.id) AS faculty_names
              FROM project p JOIN source_record s ON s.id=p.source_id ORDER BY lower(p.title),p.id''')
            items = group_project_reports(items, q)
        return render_template('entities.html', kind=kind, items=items,q=q)

    @app.get('/about-data')
    def about():
        coverage = {(r['school_code'] or 'Unassigned'): r['count'] for r in rows("SELECT school_code,count(*) FROM v_faculty_discovery d WHERE publication_collection_status IN ('PARTIAL','RETRIEVED') AND EXISTS(SELECT 1 FROM faculty_publication a WHERE a.faculty_id=d.faculty_id) GROUP BY school_code")}
        coverage.update(one('''SELECT (SELECT count(DISTINCT faculty_id) FROM faculty_publication) AS faculty,
          (SELECT count(*) FROM publication) AS publications,(SELECT count(DISTINCT faculty_id) FROM faculty_publication) AS faculty_with_papers,
          (SELECT count(*) FROM project) AS projects,(SELECT count(*) FROM lab) AS labs,
          (SELECT count(*) FROM faculty_external_profile WHERE identity_match_status='VERIFIED') AS verified_profiles'''))
        return render_template('about.html', coverage=coverage,
            departments=rows("SELECT school_code,department_name,count(*) AS count FROM v_faculty_discovery d WHERE publication_collection_status IN ('PARTIAL','RETRIEVED') AND EXISTS(SELECT 1 FROM faculty_publication a WHERE a.faculty_id=d.faculty_id) GROUP BY school_code,department_name ORDER BY school_code,department_name"))

    def safe_next():
        path = request.values.get('next', '')
        parsed = urlsplit(path)
        return path if path.startswith('/') and not path.startswith('//') and not parsed.netloc and not parsed.scheme else url_for('collaborators')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            csrf()
            account = one('SELECT * FROM user_account WHERE username=:name', name=request.form.get('username', ''))
            if account and check_password_hash(account['password_hash'], request.form.get('password', '')):
                session.clear()
                session['user_id'] = account['id']
                return redirect(safe_next())
            error = 'Username or password is incorrect.'
        return render_template('login.html', error=error)

    @app.post('/logout')
    def logout():
        csrf()
        session.clear()
        return redirect(url_for('collaborators'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        error = None
        if request.method == 'POST':
            csrf()
            name = request.form.get('username','').strip()
            password = request.form.get('password','')
            fid = request.form.get('faculty_id',type=int)
            email = request.form.get('email','').strip().casefold()
            f = person(fid) if fid else None
            if not name or len(name)>100 or len(password)<12 or not f:
                error = 'Choose a listed faculty profile, a username and a password of at least 12 characters.'
            elif email and f['email'] and email != f['email'].casefold():
                error = 'Use the institutional email recorded on the selected official profile.'
            else:
                try:
                    with engine.begin() as db:
                        uid = db.execute(text('''INSERT INTO user_account(username,password_hash,role,faculty_id)
                          VALUES(:name,:password,'FACULTY',:fid) RETURNING id'''),
                          {'name':name,'password':generate_password_hash(password),'fid':fid}).scalar_one()
                    session.clear()
                    session['user_id'] = uid
                    flash('Profile linked for this demonstration. Institutional ownership has not been verified.')
                    return redirect(url_for('collaborators'))
                except IntegrityError:
                    error = 'That username or faculty profile already has an account. Please sign in.'
        return render_template('register.html', faculty=faculty_rows(), error=error)

    @app.get('/dashboard')
    def dashboard():
        return redirect(url_for('collaborators'))

    return app
