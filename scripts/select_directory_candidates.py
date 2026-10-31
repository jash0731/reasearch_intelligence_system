#!/usr/bin/env python3
"""Select extractable directory candidates. This does not verify external identities
or publish records; publication-ready inclusion requires later author resolution.
"""
import argparse
from collections import defaultdict
import json
import re
from pathlib import Path


def select(rows):
    def name_tokens(value):
        value=re.sub(r'^(?:dr|prof|mr|mrs|ms)\.?\s*','',value or '',flags=re.I)
        return re.findall(r'[a-z0-9]+',value.lower())
    def same_name(a,b):
        x,y=name_tokens(a),name_tokens(b)
        return bool(x and y) and (set(x)==set(y) or ''.join(x)==''.join(y))
    def department(value):
        value=(value or '').lower().replace('scope-quantum-ai-faculty','quantum-ai')
        return re.sub(r'[^a-z0-9]','',value).rstrip('s')
    grouped=defaultdict(list)
    for r in rows:
        grouped[r.get('canonical_url') or r.get('source',{}).get('requested_url')].append(r)
    candidates=[]; held=[]
    known_conflicts={'https://vitdirectory.vit.ac.in/page/faculty/10483':
        'Published ORCID returned OpenAlex display name J Valarmathi; identity unresolved (19 October 2026)'}
    external_owners=defaultdict(set)
    for key, observations in grouped.items():
        for r in observations:
            for kind in ('orcid','google_scholar','scopus'):
                value=r.get('external_profiles',{}).get(kind,{}).get('url')
                if value:external_owners[(kind,value)].add(key)
    for key, observations in grouped.items():
        r=dict(observations[0]);reasons=[]
        r['roster_observations']=[o for x in observations for o in x.get('roster_observations',[])]
        if r.get('status')!='EXTRACTED':reasons.append('Official profile unavailable or unparsed')
        if not r.get('name'):reasons.append('Missing official name')
        if r.get('profile_school_code') not in {'SCOPE','SCORE'}:reasons.append('School identity unresolved')
        if not r.get('designation'):reasons.append('Missing designation')
        if not r.get('qualifications'):reasons.append('Missing academic qualifications')
        if not r.get('research_interests'):reasons.append('Missing research interests')
        if r.get('name') and not any(same_name(r['name'],o['listed_name']) for o in r['roster_observations']):
            reasons.append('Roster name and canonical profile name need reconciliation')
        if r.get('department') and not any(department(r['department'])==department(o['department_slug']) for o in r['roster_observations']):
            reasons.append('Roster department and canonical profile department need reconciliation')
        links=r.get('external_profiles',{})
        if not any(k in links for k in ('orcid','google_scholar')):reasons.append('No usable ORCID or Scholar link')
        reasons.extend(r.get('review_reasons',[]))
        if key in known_conflicts:reasons.append(known_conflicts[key])
        for kind in ('orcid','google_scholar','scopus'):
            value=links.get(kind,{}).get('url')
            if value and len(external_owners[(kind,value)])>1:
                reasons.append('External identifier shared by multiple canonical profiles: '+kind)
        r['external_identity_verification']='PENDING'
        r['publication_ready']=False
        if reasons:
            r['hold_reasons']=sorted(set(reasons));held.append(r)
        else:
            r['selection_status']='DIRECTORY_CANDIDATE; external-author verification and publication retrieval pending'
            candidates.append(r)
    return candidates,held


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path);args=parser.parse_args()
    rows=json.loads((args.directory/'faculty_profiles.json').read_text())
    candidates,held=select(rows)
    for name,data in [('directory_candidates.json',candidates),('directory_held_for_review.json',held)]:
        (args.directory/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'profiles_attempted':len(rows),'unique_candidates':len(candidates),'unique_held':len(held),
        'published':0,'note':'Curated candidates only; not a complete roster or externally verified publication dataset.'},indent=2))
