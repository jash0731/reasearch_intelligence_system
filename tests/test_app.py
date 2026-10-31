"""Workspace route checks against real PostgreSQL joins and signed sessions."""
from html.parser import HTMLParser
import pytest
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash
from research.app import create_app
from research.database.sql import initialize_schema
from research.database import models as m
from test_schema import seed_graph


class ConnectionControl(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id') in {'connection', 'connection-hint'}:
            self.elements[attrs['id']] = attrs
        if tag == 'option' and 'selected' in attrs:
            self.elements.setdefault('selected_values', []).append(attrs.get('value'))


@pytest.fixture
def workspace(postgres_database_factory):
    with postgres_database_factory() as uri:
        engine=create_engine(uri)
        initialize_schema(engine)
        with engine.begin() as db:
            _,ids,_=seed_graph(db)
            db.execute(m.faculty.update().where(m.faculty.c.id.in_(ids[:3])).values(publication_collection_status='RETRIEVED'))
            db.execute(m.user_account.insert().values(username='demo',password_hash=generate_password_hash('test-password-123'),role='FACULTY',faculty_id=ids[0]))
        app=create_app({'TESTING':True,'SECRET_KEY':'test-secret','DATABASE_URL':uri})
        yield app,ids
        app.extensions['engine'].dispose()
        engine.dispose()


def test_collaboration_page_shows_people_and_paper_witnesses(workspace):
    app,ids=workspace
    client=app.test_client()
    response=client.get('/collaborators',query_string={'faculty_id':ids[0]})
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'Bea' in html and 'Chen' in html and 'Bea and Chen' in html
    assert 'Shared research interests' in html and 'Mutual coauthor' in html
    assert 'cytoscape' not in html.lower() and '<canvas' not in html.lower()
    controls = ConnectionControl(html).elements
    assert 'disabled' not in controls['connection']
    assert 'hidden' in controls['connection-hint']
    direct=client.get('/collaborators',query_string={'faculty_id':ids[0],'connection':'direct'}).get_data(as_text=True)
    assert 'Past coauthor · 1 step' in direct and 'Mutual coauthor · 2 steps' not in direct
    two_hop=client.get('/collaborators',query_string={'faculty_id':ids[0],'connection':'two-hop'}).get_data(as_text=True)
    assert 'Mutual coauthor · 2 steps' in two_hop and 'Past coauthor · 1 step' not in two_hop
    assert client.get('/network?faculty_id='+str(ids[0])).location.endswith('/collaborators?faculty_id='+str(ids[0]))


def test_literal_keyword_and_missing_publications(workspace):
    app,ids=workspace
    client=app.test_client()
    assert 'Alice and Bea' in client.get('/collaborators?q=Alice').get_data(as_text=True)
    for mode in ('direct', 'two-hop', 'new'):
        html = client.get('/collaborators', query_string={'q':'Alice', 'connection':mode}).get_data(as_text=True)
        controls = ConnectionControl(html).elements
        assert 'disabled' in controls['connection']
        assert 'hidden' not in controls['connection-hint']
        assert 'Choose a researcher to filter by coauthor connection.' in html
        assert 'all' in controls['selected_values'] and mode not in controls['selected_values']
        assert 'Publication keyword match' in html
    assert 'No matches in the collected records' in client.get('/collaborators?q=%25').get_data(as_text=True)
    assert client.get('/faculty/'+str(ids[3])).status_code==404
    assert 'Dev' not in client.get('/faculty').get_data(as_text=True)
    for route in ['/faculty','/publications','/about-data','/labs','/projects','/login','/register','/health']:
        assert client.get(route).status_code==200,route


def test_login_uses_linked_profile_and_rejects_csrf_and_external_redirect(workspace):
    app,ids=workspace
    client=app.test_client()
    assert client.post('/login',data={'username':'demo','password':'test-password-123'}).status_code==400
    client.get('/login')
    with client.session_transaction() as state:token=state['csrf_token']
    response=client.post('/login',data={'username':'demo','password':'test-password-123','csrf_token':token,'next':'https://example.org/evil'})
    assert response.status_code==302 and response.location.endswith('/collaborators')
    assert 'Exploring connections for' in client.get('/collaborators').get_data(as_text=True)
    keyword_only = client.get('/collaborators', query_string={'faculty_id':'', 'q':'Alice'})
    assert keyword_only.status_code == 200
    html = keyword_only.get_data(as_text=True)
    assert 'Exploring connections for' not in html
    assert 'Publication keyword match' in html
    assert 'disabled' in ConnectionControl(html).elements['connection']
    # Leaving the selection empty does not clear the linked account preference.
    assert 'Exploring connections for' in client.get('/collaborators').get_data(as_text=True)
    assert client.get('/logout').status_code==405


def test_registration_links_existing_profile_and_never_creates_faculty(workspace):
    app,ids=workspace
    client=app.test_client()
    client.get('/register')
    with client.session_transaction() as state:token=state['csrf_token']
    response=client.post('/register',data={'username':'newfaculty','password':'test-password-123','faculty_id':ids[2],'csrf_token':token})
    assert response.status_code==302
    with app.extensions['engine'].connect() as db:
        assert db.scalar(text('SELECT count(*) FROM faculty'))==4
        assert db.scalar(text("SELECT faculty_id FROM user_account WHERE username='newfaculty'"))==ids[2]
