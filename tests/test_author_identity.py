"""Boundary checks for author identity and complete pagination; no live API calls."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('enrich',Path(__file__).parents[1]/'scripts'/'enrich_directory.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_names_accept_reordering_and_initial_expansion_without_prefix_guessing():
 assert m.compatible_name('Dr. Saraswathi Priyadharshini A','A. Saraswathi Priyadharshini')
 assert m.compatible_name('Dr. Boominathan P','Boominathan Perumal')
 assert not m.compatible_name('Dr. Anbarasi M','J. Valarmathi')
 assert not m.compatible_name('Dr. Anand R','Anand Rajesh Kumar')
 assert not m.compatible_name('Dr. Raj Kumar','Rajesh Kumar')

class FakeClient:
 def __init__(self,display='A. Saraswathi Priyadharshini',institution=m.VIT,orcid='https://orcid.org/0000-0001-5010-5968'):
  self.calls=[];self.display=display;self.institution=institution;self.orcid=orcid
 def get(self,url):
  self.calls.append(url);meta={'retrieved_at':'2026-10-20T00:00:00+00:00','sha256':'a'*64}
  if '/authors/' in url:return {'id':'https://openalex.org/A1','display_name':self.display,'orcid':self.orcid,'affiliations':[{'institution':{'id':self.institution}}],'summary_stats':{'h_index':3,'i10_index':2}},meta
  if 'cursor=%2A' in url:return {'meta':{'count':101,'next_cursor':'page2'},'results':[{'id':f'https://openalex.org/W{i}'} for i in range(100)]},meta
  return {'meta':{'count':101,'next_cursor':None},'results':[{'id':'https://openalex.org/W100'}]},meta

def profile():return {'canonical_url':'https://vitdirectory.vit.ac.in/page/faculty/17977','name':'Dr. Saraswathi Priyadharshini A','external_profiles':{'orcid':{'url':'https://orcid.org/0000-0001-5010-5968'}}}

def test_exact_orcid_alone_never_attaches_conflicting_persons_papers():
 client=FakeClient(display='J. Valarmathi');faculty,works,review=m.process(profile(),client)
 assert faculty is None and works==[] and review['reason']=='DISPLAYED_NAME_CONFLICT'
 assert len(client.calls)==1

def test_matching_name_without_vit_evidence_is_held():
 faculty,works,review=m.process(profile(),FakeClient(institution='https://openalex.org/I_OTHER'))
 assert faculty is None and not works and review['reason']=='NO_VIT_AFFILIATION_EVIDENCE'

def test_author_collection_follows_cursor_beyond_first_page():
 client=FakeClient();faculty,works,review=m.process(profile(),client)
 assert review is None and len(works)==101 and faculty['publication_collection_status']=='RETRIEVED'
 assert len(client.calls)==3
 assert faculty['metrics']['i10_index']==2
 assert faculty['metrics']['cited_by_count'] is None

def test_duplicate_provider_author_rows_preserve_identity_but_not_ambiguous_order():
 rows=[{'author':{'id':'https://openalex.org/A1'}},{'author':{'id':'https://openalex.org/A1'}},{'author':{'id':'https://openalex.org/A2'}}]
 links=m.authorship_rows(rows,{'https://openalex.org/A1':{'source_key':'vit:profile:1'},'https://openalex.org/A2':{'source_key':'vit:profile:2'}},'openalex:work:W1','https://api.openalex.org/works/W1')
 assert len(links)==2 and all(a['author_order'] is None for a in links)
 assert len(rows)==3

def test_restricted_cursor_uses_documented_basic_paging_below_ten_thousand():
 class RestrictedClient(FakeClient):
  def get(self,url):
   if 'cursor=page2' in url:raise RuntimeError('HTTP_401')
   return super().get(url)
 faculty,works,review=m.process(profile(),RestrictedClient())
 assert review is None and len(works)==101 and faculty['publication_collection_status']=='RETRIEVED'
