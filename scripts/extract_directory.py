#!/usr/bin/env python3
"""Collect public VIT Vellore SCOPE/SCORE directory evidence, without importing it.

Uses standard-library HTML parsing. Resumable cache; no guessed employee IDs,
no name-only identity merges, and no fabricated zero metrics or publication lists.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)

    def text(self):
        def parts(n):
            if isinstance(n, str):
                yield n
            elif n.tag not in {'script', 'style'}:
                for c in n.children:
                    yield from parts(c)
        return re.sub(r'\s+', ' ', ' '.join(parts(self))).strip()

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Tree(HTMLParser):
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.current)
        self.current.children.append(n)
        if tag not in self.VOID:
            self.current = n

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        n = self.current
        while n.parent is not None:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent

    def handle_data(self, data):
        self.current.children.append(data)


def useful(value):
    return value and value.strip().lower() not in {'-', '--', 'n/a', 'nil', 'na', 'none', ':'}


def parse_profile(html, url):
    tree = Tree(html).root
    sections = {n.attrs['id']: n for n in tree.walk('section') if n.attrs.get('id')}
    about = sections.get('about')
    if about is None or not list(about.walk('h1')):
        if 'faculty details not found' in tree.text().lower():
            return {'status':'PROFILE_NOT_FOUND','reason':'Official directory returns a faculty-not-found page (HTTP success does not establish a profile)'}
        return {'status': 'UNPARSED', 'reason': 'No canonical faculty about section'}
    result = {'status': 'EXTRACTED', 'canonical_url': url,
              'name': next(about.walk('h1')).text(), 'designation': None,
              'school': None, 'department': None, 'institutional_emails': [],
              'qualifications': [], 'research_interests': [], 'external_profiles': {},
              'source_reported_metrics': {}, 'contributions': [], 'review_reasons': []}
    for strong in about.walk('strong'):
        key = strong.text().strip(' :').lower()
        out = {'designation':'designation','school / centre':'school','department':'department'}.get(key)
        if out and strong.parent:
            idx = strong.parent.children.index(strong)
            bits = []
            for n in strong.parent.children[idx+1:]:
                if isinstance(n, Node) and n.tag in {'br', 'strong'}:
                    break
                bits.append(n if isinstance(n,str) else n.text())
            value = re.sub(r'\s+', ' ', ' '.join(bits)).strip(' :')
            result[out] = value if useful(value) else None
    for anchor in tree.walk('a'):
        href = anchor.attrs.get('href', '')
        if href.lower().startswith('mailto:'):
            mail = href[7:].split('?')[0].strip()
            if mail.lower().endswith('@vit.ac.in'):
                result['institutional_emails'].append(mail)
    education = sections.get('educational-details')
    if education:
        for n in education.walk('div'):
            if n.has_class('justify-content-between'):
                institution = next(n.walk('h3'),None)
                sub = next((d for d in n.walk('div') if d.has_class('subheading')),None)
                result['qualifications'].append({'institution':institution.text() if institution else None,
                    'qualification':sub.text() if sub else None, 'source_text':n.text()})
    research = sections.get('research-details')
    if research:
        result['research_interests'] = [li.text() for li in research.walk('li') if useful(li.text())]
        for img in research.walk('img'):
            kind = img.attrs.get('src','').rsplit('/',1)[-1].lower()
            parent = img.parent
            a = next(parent.walk('a'),None)
            raw = a.attrs.get('href','').strip() if a else ''
            text = a.text() if a else ''
            if 'orcid' in kind:
                m = re.search(r'\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b', raw+' '+text, re.I)
                if m:
                    # ISO 7064 MOD 11-2 checksum, including terminal X.
                    digits = m[0].replace('-','').upper(); total = 0
                    for d in digits[:-1]: total = (total + int(d))*2
                    check = (12-total%11)%11
                    if digits[-1] == ('X' if check==10 else str(check)):
                        result['external_profiles']['orcid'] = {'url':'https://orcid.org/'+m[0], 'source_value':raw or text}
                    else: result['review_reasons'].append('Invalid ORCID checksum: '+m[0])
            elif 'google-scholar' in kind:
                m = re.search(r'[?&]user=([A-Za-z0-9_-]+)',raw)
                ident = m[1] if m else raw.split('&',1)[0]
                if re.fullmatch(r'[A-Za-z0-9_-]{6,64}',ident):
                    result['external_profiles']['google_scholar'] = {'url':'https://scholar.google.com/citations?user='+ident,'source_value':raw}
                elif useful(raw): result['review_reasons'].append('Malformed Scholar identifier: '+raw)
            elif 'scopus' in kind:
                m = re.search(r'(?:authorId=)?(\d{6,})',raw)
                if m: result['external_profiles']['scopus'] = {'url':'https://www.scopus.com/authid/detail.uri?authorId='+m[1],'source_value':raw}
            elif 'hindex' in kind or 'i10index' in kind:
                span = next(parent.walk('span'),None)
                value = span.text() if span else ''
                if value.isdigit():
                    key = 'i10_index' if 'i10' in kind else 'h_index'
                    result['source_reported_metrics'][key] = {'value':int(value),'provider':'VIT faculty profile (underlying provider unspecified)','metric_as_of':None}
    for sid, section in sections.items():
        if sid in {'about','research-details','educational-details','other-details'}: continue
        heading = next(section.walk('h2'),None)
        for table in section.walk('table'):
            rows = [[c.text() for c in row.children if isinstance(c,Node) and c.tag in {'td','th'}] for row in table.walk('tr')]
            if not rows: continue
            for row in rows[1:]:
                if row and useful(row[0]):
                    result['contributions'].append({'section':sid,'label':heading.text() if heading else sid,'headers':rows[0],'values':row})
    other = sections.get('other-details')
    if other:
        for a in other.walk('a'):
            href = a.attrs.get('href','')
            if href.startswith(('https://','http://')):
                result['external_profiles'].setdefault('other',[]).append({'url':href,'label':a.text()})
    school = (result['school'] or '').lower()
    result['profile_school_code'] = ('SCOPE' if school=='school of computer science and engineering' else
        'SCORE' if school=='school of computer science engineering and information systems' else None)
    if not result['profile_school_code']:
        result['review_reasons'].append('Canonical school is missing or outside SCOPE/SCORE')
    result['publication_collection_status'] = 'NOT_ATTEMPTED'
    return result


def parse_roster(html, url):
    tree = Tree(html).root
    code = 'SCORE' if '/score/' in url else 'SCOPE'
    rows = []
    for a in tree.walk('a'):
        if not a.has_class('exad-post-grid-title'): continue
        article = a.parent
        while article.parent and article.tag!='article': article=article.parent
        category = next((n for n in article.walk('ul') if n.has_class('exad-post-grid-category')),None)
        href = urljoin(url,a.attrs.get('href',''))
        if urlparse(href).hostname not in {'vit.ac.in','vitdirectory.vit.ac.in'}:continue
        rows.append({'listed_name':a.text(),'listed_designation':category.text() if category else None,
            'school_code':code,'department_slug':url.rsplit('/',1)[-1],
            'campus':'Vellore','roster_url':url,'profile_url':href})
    return rows


def write_json(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=0,help='0 fetches all discovered profile URLs')
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    cache=root/'raw';cache.mkdir(exist_ok=True)
    fetched=datetime.now(timezone.utc).isoformat()
    def fetch(url):
        key=hashlib.sha256(url.encode()).hexdigest()
        bodypath=cache/(key+'.html');metapath=cache/(key+'.json')
        if bodypath.exists() and metapath.exists():
            return bodypath.read_text(),json.loads(metapath.read_text())
        time.sleep(.3)
        try:
            req=Request(url,headers={'User-Agent':'VIT-Research-Intelligence-DBMS-Project/2.0 (public faculty directory collection)'})
            with urlopen(req,timeout=25) as response:
                body=response.read();final=response.url
            meta={'requested_url':url,'final_url':final,'retrieved_at':datetime.now(timezone.utc).isoformat(),
                  'status':'FETCHED','sha256':hashlib.sha256(body).hexdigest()}
            bodypath.write_bytes(body);write_json(metapath,meta)
            return body.decode('utf-8','replace'),meta
        except Exception as exc:
            return '',{'requested_url':url,'status':'FAILED','error':str(exc),'retrieved_at':datetime.now(timezone.utc).isoformat()}
    seeds=['https://vit.ac.in/faculty','https://vit.ac.in/schools/school-of-computer-science-engineering-and-information-systems']
    seeds.append('https://vit.ac.in/schools/school-of-computer-science-and-engineering')
    source_results=[];urls=set()
    for u in seeds:
        html,meta=fetch(u);source_results.append(meta)
        for a in Tree(html).root.walk('a'):
            href=urljoin(u,a.attrs.get('href',''))
            if re.fullmatch(r'https://vit\.ac\.in/(school/allfaculty/(scope|score)/[^/?#]+|scope-quantum-ai-faculty)/?',href):urls.add(href.rstrip('/'))
    listings=[]
    for u in sorted(urls):
        html,meta=fetch(u);rows=parse_roster(html,u);meta['listing_count']=len(rows)
        source_results.append(meta);listings.extend(rows)
        print('ROSTER',u,len(rows),meta['status'],flush=True)
    write_json(root/'roster_listings.json',listings)
    write_json(root/'roster_sources.json',source_results)
    by_url={}
    for row in listings:by_url.setdefault(row['profile_url'],[]).append(row)
    profiles=[];targets=sorted(by_url)
    if args.limit: targets=targets[:args.limit]
    def collect(u):
        html,meta=fetch(u)
        p=parse_profile(html,meta.get('final_url',u)) if html else {'status':'FAILED'}
        p.update({'source':meta,'roster_observations':by_url[u]})
        if p.get('profile_school_code') and any(r['school_code']!=p['profile_school_code'] for r in by_url[u]):
            p['review_reasons'].append('Roster school and canonical profile school conflict')
        return p
    with ThreadPoolExecutor(max_workers=max(1,min(3,args.workers))) as pool:
        futures={pool.submit(collect,u):u for u in targets}
        for future in as_completed(futures):
            try: p=future.result()
            except Exception as exc:p={'status':'FAILED','source':{'requested_url':futures[future]},'error':str(exc)}
            profiles.append(p)
            write_json(root/'faculty_profiles.json',sorted(profiles,key=lambda p:p['source']['requested_url']))
            if len(profiles)%20==0:print('PROFILES',len(profiles),'/',len(targets),flush=True)
    extracted=[p for p in profiles if p['status']=='EXTRACTED']
    canonical={p['canonical_url'] for p in extracted}
    report={'started_at':fetched,'finished_at':datetime.now(timezone.utc).isoformat(),
        'scope':{'campus':'Vellore','schools':['SCOPE','SCORE']},
        'roster_listing_observations':len(listings),'unique_profile_links':len(by_url),
        'listings_by_school':{s:sum(r['school_code']==s for r in listings) for s in ['SCOPE','SCORE']},
        'profiles_attempted':len(profiles),'profiles_extracted':len(extracted),
        'distinct_canonical_profiles':len(canonical),'profiles_failed_or_unparsed':len(profiles)-len(extracted),
        'with_orcid':sum('orcid' in p['external_profiles'] for p in extracted),
        'with_scholar':sum('google_scholar' in p['external_profiles'] for p in extracted),
        'with_h_index':sum('h_index' in p['source_reported_metrics'] for p in extracted),
        'with_i10_index':sum('i10_index' in p['source_reported_metrics'] for p in extracted),
        'with_qualifications':sum(bool(p['qualifications']) for p in extracted),
        'with_contributions':sum(bool(p['contributions']) for p in extracted),
        'profiles_needing_review':sum(bool(p['review_reasons']) for p in extracted),
        'failed_roster_sources':[r for r in source_results if r['status']=='FAILED'],
        'publication_retrieval':'NOT_ATTEMPTED; this pass extracts official directory evidence only',
        'not_imported':True,
        'notes':['Listing counts are observations, not verified headcounts.',
                 'Canonical profile IDs are source identifiers, not inferred employee IDs.',
                 'Metrics are reported by VIT profiles; underlying provider and metric dates are not assumed.',
                 'School conflicts remain for review. No names are used to merge distinct source identities.',
                 'Raw HTML is source evidence only; normalized output omits mobile numbers.']}
    write_json(root/'quality_report.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
