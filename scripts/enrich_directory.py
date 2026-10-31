#!/usr/bin/env python3
"""Verified ORCID enrichment. Public API only; explicit identity checks; immutable batches.
Docs: https://help.openalex.org/data/authors/ and /api/paging/.
Run separately from the offline loader. Never scrapes Google Scholar.
"""
from __future__ import annotations
import argparse, collections, concurrent.futures, csv, hashlib, json, os, re, threading, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

BASE='https://api.openalex.org'; VIT='https://openalex.org/I876193797'
def now(): return datetime.now(timezone.utc).isoformat()
def dump(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def tokens(s):
 s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
 return [x for x in re.findall('[a-z]+',s) if x not in {'dr','prof','professor','mr','mrs','ms'}]
def compatible_name(official,display):
 a,b=tokens(official),tokens(display)
 if not a or not b or len(a)!=len(b): return False
 # An initial may expand, but at least one substantive name must be identical.
 if not any(len(x)>=4 and x in b for x in a): return False
 def match(xs,ys):
  if not xs:return True
  x=xs[0]
  for i,y in enumerate(ys):
   if x==y or (min(len(x),len(y))==1 and x[0]==y[0]):
    if match(xs[1:],ys[:i]+ys[i+1:]):return True
  return False
 return match(a,b)

class Client:
 def __init__(self,folder,offline=False): self.folder=folder;self.offline=offline;self.lock=threading.Lock();self.stats=collections.Counter()
 def get(self,url):
  key=hashlib.sha256(url.encode()).hexdigest();body=self.folder/(key+'.json');meta=self.folder/(key+'.meta.json')
  if body.exists() and meta.exists():return json.loads(body.read_text()),json.loads(meta.read_text())
  if self.offline:raise RuntimeError('NO_CACHED_RESPONSE')
  for attempt in range(2):
   try:
    with urlopen(Request(url,headers={'User-Agent':'VIT-Research-DBMS-Educational-Collector/2.0','Accept':'application/json'}),timeout=35) as response:
     content=response.read(); obj=json.loads(content)
    metadata={'requested_url':url,'retrieved_at':now(),'sha256':hashlib.sha256(content).hexdigest(),'status':'FETCHED'}
    body.write_bytes(content);dump(meta,metadata)
    with self.lock:self.stats['requests']+=1
    return obj,metadata
   except HTTPError as e:
    if e.code==404: raise RuntimeError('ORCID_NOT_FOUND') from e
    if e.code in (429,403):raise RuntimeError('PROVIDER_BUDGET_OR_ACCESS_LIMIT_'+str(e.code)) from e
    if attempt:raise RuntimeError('HTTP_'+str(e.code)) from e
    time.sleep(1)
   except (URLError,TimeoutError) as e:
    if attempt:raise RuntimeError('NETWORK_FETCH_FAILED') from e
    time.sleep(1)

def process(profile,client):
 key='vit:profile:'+profile['canonical_url'].rstrip('/').rsplit('/',1)[-1]
 orcid=(profile.get('external_profiles',{}).get('orcid') or {}).get('url')
 review={'faculty_source_key':key,'faculty_name':profile['name'],'official_profile_url':profile['canonical_url']}
 if not orcid:return None,[],dict(review,reason='NO_ORCID; Scholar outbound link retained, no author search guessed')
 author_url=BASE+'/authors/'+orcid
 try: author,meta=client.get(author_url)
 except RuntimeError as e:return None,[],dict(review,reason=str(e))
 aid=author.get('id'); review.update(candidate_openalex_id=aid,candidate_name=author.get('display_name'))
 if len(set(author.get('observed_orcids',[])))>1:return None,[],dict(review,reason='MULTIPLE_PROVIDER_ORCIDS_NEEDS_REVIEW')
 if author.get('orcid')!=orcid and orcid not in author.get('observed_orcids',[]):
  return None,[],dict(review,reason='ORCID_NOT_EXACT')
 if not compatible_name(profile['name'],author.get('display_name')):
  return None,[],dict(review,reason='DISPLAYED_NAME_CONFLICT')
 insts={x.get('institution',{}).get('id') for x in author.get('affiliations',[])}|{x.get('id') for x in author.get('last_known_institutions',[]) or []}
 if VIT not in insts:return None,[],dict(review,reason='NO_VIT_AFFILIATION_EVIDENCE')
 stats=author.get('summary_stats') or {}
 out={'source_key':key,'openalex_id':aid,'display_name':author['display_name'],'source_url':author_url,'external_orcid':orcid,
      'identity_evidence':{'method':'EXACT_OFFICIAL_ORCID_AND_COMPATIBLE_DISPLAYED_NAME_AND_VIT_AFFILIATION','official_profile_url':profile['canonical_url'],'official_name':profile['name'],'provider_display_name':author['display_name'],'affiliation_ids':sorted(x for x in insts if x),'source_sha256':meta['sha256']},
      'retrieved_at':meta['retrieved_at'],'publication_collection_status':'RETRIEVED','metrics':{'provider':'OpenAlex','observed_at':meta['retrieved_at'],'h_index':stats.get('h_index'),'i10_index':stats.get('i10_index'),'cited_by_count':author.get('cited_by_count'),'works_count':author.get('works_count')}}
 works=[];cursor='*';total=None;seen=set()
 try:
  while cursor:
   url=BASE+'/works?'+urlencode({'filter':'authorships.author.id:'+aid.rsplit('/',1)[-1]+',from_publication_date:2019-01-01','per_page':100,'cursor':cursor})
   try:page,pmeta=client.get(url)
   except RuntimeError:
    # OpenAlex basic paging is documented below10,000; some unauthenticated cursor requests are restricted.
    if cursor=='*' or total is None or total>10000:raise
    fallback=BASE+'/works?'+urlencode({'filter':'authorships.author.id:'+aid.rsplit('/',1)[-1]+',from_publication_date:2019-01-01','per_page':100,'page':len(works)//100+1})
    page,pmeta=client.get(fallback)
   total=page.get('meta',{}).get('count',total)
   for work in page.get('results',[]):
    if work.get('id') not in seen:
     seen.add(work.get('id'));works.append((work,pmeta))
   next_cursor=page.get('meta',{}).get('next_cursor')
   if not page.get('results') or len(works)>=(total or 0):break
   if not next_cursor or next_cursor==cursor:raise RuntimeError('PAGINATION_INCOMPLETE')
   cursor=next_cursor
  if total is not None and len(works)<total:raise RuntimeError('PAGINATION_INCOMPLETE')
 except RuntimeError as e:
  out['publication_collection_status']='PARTIAL' if works else 'FETCH_FAILED'
  out['collection_error']=str(e)
 out['collected_publications_since_2019']=len(works);out['provider_reported_publications_since_2019']=total
 return out,works,None


def authorship_rows(provider_authors,faculty_map,publication_key,source_url):
 counts=collections.Counter((a.get('author') or {}).get('id') for a in provider_authors)
 ambiguous_order=any(n>1 for aid,n in counts.items() if aid)
 linked=set();rows=[]
 for position,a in enumerate(provider_authors,1):
  aid=(a.get('author') or {}).get('id')
  if aid not in faculty_map or aid in linked:continue
  linked.add(aid)
  rows.append({'faculty_source_key':faculty_map[aid]['source_key'],'publication_source_key':publication_key,'author_order':None if ambiguous_order else position,'is_corresponding':a.get('is_corresponding'),'identity_match_status':'VERIFIED','source_url':source_url})
 return rows

def build(args):
 input_source_path=Path(args.input); folder=Path(args.evidence);folder.mkdir(parents=True,exist_ok=True);cache=folder/'responses';cache.mkdir(exist_ok=True)
 if Path(args.output).exists():raise SystemExit('Refusing to mutate existing closed output')
 profiles=json.loads(input_source_path.read_text());profiles=profiles[:args.limit] if args.limit else profiles
 client=Client(cache,offline=args.offline);faculty=[];allworks={};review=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(process,p,client):p for p in profiles}
  for n,future in enumerate(concurrent.futures.as_completed(futures),1):
   f,works,r=future.result()
   if f:faculty.append(f)
   if r:review.append(r)
   for w,m in works:allworks[w['id']]=(w,m)
   if n%10==0:print(json.dumps({'processed':n,'verified_faculty':len(faculty),'unique_works':len(allworks),'review':len(review)}),flush=True)
 # Refuse one OpenAlex identity linked to multiple internal identities.
 counts=collections.Counter(f['openalex_id'] for f in faculty);duplicates={k for k,v in counts.items() if v>1}
 if duplicates:
  for f in faculty:
   if f['openalex_id'] in duplicates:review.append({'faculty_source_key':f['source_key'],'reason':'SHARED_OPENALEX_ID','candidate_openalex_id':f['openalex_id']})
  faculty=[f for f in faculty if f['openalex_id'] not in duplicates]
 fmap={f['openalex_id']:f for f in faculty};pubs=[];authorships=[];publication_reviews=[]
 doi_best={}
 for wid,(w,meta) in sorted(allworks.items()):
  doi=(w.get('doi') or '').lower()
  if doi:
   previous=doi_best.get(doi)
   if previous is None or (w.get('cited_by_count') or 0)>(allworks[previous][0].get('cited_by_count') or 0):doi_best[doi]=wid
 for wid,(w,meta) in sorted(allworks.items()):
  doi=(w.get('doi') or '').lower()
  if doi and doi_best[doi]!=wid:
   publication_reviews.append({'source_key':wid,'reason':'EXACT_DOI_DUPLICATE_SUPPRESSED','canonical_source_key':doi_best[doi]});continue
  if not (w.get('title') or w.get('display_name')):
   publication_reviews.append({'source_key':wid,'reason':'MISSING_PUBLICATION_TITLE'});continue
  # Keep only papers with at least one selected, verified internal author.
  wa=w.get('authorships',[])
  if not any((a.get('author') or {}).get('id') in fmap for a in wa):continue
  source=(w.get('primary_location') or {}).get('source') or {};venue=None
  if source.get('id') and source.get('display_name'):
   venue={'source_key':'openalex:source:'+source['id'].rsplit('/',1)[-1],'name':source['display_name'],'kind':source.get('type'),'issn_l':source.get('issn_l'),'source_url':source['id']}
  pubkey='openalex:work:'+wid.rsplit('/',1)[-1];url=BASE+'/works/'+wid.rsplit('/',1)[-1]
  raw=[{'name':a.get('raw_author_name') or (a.get('author') or {}).get('display_name'),'openalex_id':(a.get('author') or {}).get('id'),'orcid':(a.get('author') or {}).get('orcid'),'institutions':a.get('institutions',[])} for a in wa]
  pubs.append({'source_key':pubkey,'title':w.get('title') or w.get('display_name'),'year':w.get('publication_year'),'publication_date':w.get('publication_date'),'doi':w.get('doi'),'citations':w.get('cited_by_count'),'citations_provider':'OpenAlex','citations_observed_at':meta['retrieved_at'],'kind':w.get('type'),'venue':venue,'raw_authors':raw,'source_url':url,'retrieved_at':meta['retrieved_at'],'source_sha256':meta['sha256']})
  if len({(a.get('author') or {}).get('id') for a in wa})<len(wa):publication_reviews.append({'source_key':wid,'reason':'DUPLICATE_PROVIDER_AUTHOR_ROWS; original order unknown; raw evidence retained'})
  authorships.extend(authorship_rows(wa,fmap,pubkey,url))
 result={'contract_version':2,'faculty':sorted(faculty,key=lambda f:f['source_key']),'publications':pubs,'authorships':authorships,'review':review,'publication_reviews':publication_reviews}
 output=Path(args.output);tmp=output.with_name(output.name+'.partial');tmp.mkdir(parents=True)
 dump(tmp/'enrichment.json',result)
 pairs=collections.Counter()
 bypub=collections.defaultdict(set)
 for a in authorships:bypub[a['publication_source_key']].add(a['faculty_source_key'])
 for ids in bypub.values():
  ids=sorted(ids)
  for i,a in enumerate(ids):
   for b in ids[i+1:]:pairs[a,b]+=1
 report={'attempted_faculty':len(profiles),'verified_faculty':len(faculty),'faculty_with_papers':len({a['faculty_source_key'] for a in authorships}),'unique_publications_since_2019':len(pubs),'verified_authorships':len(authorships),'direct_internal_coauthor_pairs':len(pairs),'reviews':len(review),'collection_statuses':dict(collections.Counter(f['publication_collection_status'] for f in faculty)),'review_reasons':dict(collections.Counter(r['reason'] for r in review)),'source':str(input_source_path),'publication_reviews':len(publication_reviews),'generated_at':now(),'provider':'OpenAlex','api_requests':client.stats['requests'],'notes':['ORCID exact match, compatible displayed name and VIT affiliation required. Vellore school evidence comes from official directory.','Publication coverage since 2019; provider career metrics cover provider full author profile.','No Google Scholar scraping. No inferred labs, interests, or supervision.','Exact DOI duplicates suppressed; originals retained in response cache and publication_reviews. Untitled provider rows held.']}
 dump(tmp/'quality_report.json',report)
 with (tmp/'author_review.csv').open('w',newline='',encoding='utf-8') as h:
  cols=['faculty_source_key','faculty_name','official_profile_url','candidate_openalex_id','candidate_name','reason'];wr=csv.DictWriter(h,fieldnames=cols,extrasaction='ignore');wr.writeheader();wr.writerows(review)
 data=(tmp/'enrichment.json').read_bytes();dump(tmp/'manifest.json',{'contract_version':2,'status':'complete','batch_id':output.name,'generated_at':now(),'files':{'enrichment.json':{'rows':len(pubs),'sha256':hashlib.sha256(data).hexdigest()}}})
 tmp.rename(output);print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',default='data/collection/vellore_directory_2026-10-19/directory_candidates.json');p.add_argument('--evidence',default='data/collection/enrichment_openalex_2026-10-20');p.add_argument('--output',default='data/staging/batch_005_verified_publications');p.add_argument('--workers',type=int,default=5);p.add_argument('--limit',type=int,default=0);p.add_argument('--offline',action='store_true',help='Use cached responses only; missing responses enter review');build(p.parse_args())
