#!/usr/bin/env python3
"""Cache official SCOPE facilities and literal section text, without member inference."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request,urlopen
from extract_directory import Tree

ROOT=Path(__file__).resolve().parents[1]
SLUGS=['cloud-computing-lab','machine-vision-lab','intel-multicore-lab','iot-lab',
 'block-chain-technology-lab-web3-lab','devops-automation-lab','artificial-intelligence-lab',
 'speech-and-natural-language-processing-lab','gen-ai-lab','quantum-computing-lab',
 'big-data-analytics-lab','high-performance-computing-lab']


def collect(slug):
    url='https://vit.ac.in/scope/facilities/'+slug
    raw=urlopen(Request(url,headers={'User-Agent':'VIT student DBMS source collection'}),timeout=35).read()
    tree=Tree(raw.decode('utf-8')).root
    main=next(tree.walk('main'))
    headings=list(main.walk('h2'))
    if not headings:raise ValueError('Missing facility heading')
    name=headings[0].text()
    body=main.text()
    overview=body.split('Overview',1)[-1]
    description=overview.split('Objectives',1)[0].split('Research Publications',1)[0].strip()
    if len(description)>2500:description=description[:2500]
    # Keep source-declared focus strings; no inferred keyword memberships.
    areas=[]
    focus=next((h for h in headings if h.text().casefold()=='key focus areas'),None)
    if focus:
        widget=focus.parent
        container=widget.parent if widget else None
        if container and container.parent:
            siblings=container.parent.children
            for n in siblings[siblings.index(container)+1:]:
                if not hasattr(n,'walk'):continue
                if list(n.walk('h2')):break
                for li in n.walk('li'):
                    term=li.text()
                    if term and len(term)<180:areas.append(term)
    sha=hashlib.sha256(raw).hexdigest()
    dest=ROOT/'data/collection/facilities_2026-10-20'
    dest.mkdir(parents=True,exist_ok=True)
    (dest/(slug+'.html')).write_bytes(raw)
    return {'name':name,'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),
      'sha256':sha,'description':description,'areas':list(dict.fromkeys(areas)),
      'faculty_membership':'NOT_ESTABLISHED','source_text':body}


if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:labs=list(pool.map(collect,SLUGS))
    target=ROOT/'data/staging/labs.json'
    target.write_text(json.dumps({'status':'complete','labs':labs},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'facilities':len(labs),'declared_topics':sum(len(l['areas']) for l in labs),'memberships':0}))
