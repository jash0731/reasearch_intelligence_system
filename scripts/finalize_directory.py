#!/usr/bin/env python3
"""Reparse the collected cache and report curated faculty-directory counts offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from extract_directory import parse_profile, write_json
from select_directory_candidates import select


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args();root=args.directory
    report=json.loads((root/'quality_report.json').read_text())
    rows=json.loads((root/'faculty_profiles.json').read_text())
    assert report['profiles_attempted']==report['unique_profile_links'], 'Initial full collection has not completed'
    updated=[]
    for old in rows:
        source=old['source'];url=source['requested_url']
        body=root/'raw'/(hashlib.sha256(url.encode()).hexdigest()+'.html')
        if not body.exists():updated.append(old);continue
        row=parse_profile(body.read_text(errors='replace'),source.get('final_url',url))
        row.update({'source':source,'roster_observations':old['roster_observations']})
        if row.get('profile_school_code') and any(o['school_code']!=row['profile_school_code'] for o in row['roster_observations']):
            row['review_reasons'].append('Roster school and canonical profile school conflict')
        updated.append(row)
    write_json(root/'faculty_profiles.json',updated)
    candidates,held=select(updated)
    write_json(root/'directory_candidates.json',candidates)
    write_json(root/'directory_held_for_review.json',held)
    states=Counter(r['status'] for r in updated)
    extracted=[r for r in updated if r['status']=='EXTRACTED']
    for field,expression in {
        'profiles_extracted':len(extracted),
        'profiles_failed_or_unparsed':len(updated)-len(extracted),
        'distinct_canonical_profiles':len({r['canonical_url'] for r in extracted}),
        'with_orcid':sum('orcid' in r['external_profiles'] for r in extracted),
        'with_scholar':sum('google_scholar' in r['external_profiles'] for r in extracted),
        'with_h_index':sum('h_index' in r['source_reported_metrics'] for r in extracted),
        'with_i10_index':sum('i10_index' in r['source_reported_metrics'] for r in extracted),
    }.items():report[field]=expression
    report['extraction_status_counts']=dict(states)
    report['curated_directory_candidates']=len(candidates)
    report['held_unique_source_profiles']=len(held)
    report['curation_is_not_external_identity_verification']=True
    write_json(root/'quality_report.json',report)
    school=Counter(r['profile_school_code'] for r in candidates)
    depts=Counter((r['profile_school_code'],r['department']) for r in candidates)
    numbers={
        'scope':'VIT Vellore SCOPE and SCORE; faculty only',
        'roster_listing_observations':report['roster_listing_observations'],
        'profile_links_attempted':len(updated),
        'official_profiles_extracted':len(extracted),
        'distinct_extracted_canonical_profiles':report['distinct_canonical_profiles'],
        'selected_directory_candidates':len(candidates),
        'faculty':len(candidates),
        'phd_scholars':'excluded','undergraduate_students':'excluded',
        'by_school':dict(school),
        'by_department':[{'school':s,'department':d,'faculty':n} for (s,d),n in sorted(depts.items())],
        'selected_with_orcid':sum('orcid' in r['external_profiles'] for r in candidates),
        'selected_with_scholar':sum('google_scholar' in r['external_profiles'] for r in candidates),
        'selected_with_h_index':sum('h_index' in r['source_reported_metrics'] for r in candidates),
        'selected_with_i10_index':sum('i10_index' in r['source_reported_metrics'] for r in candidates),
        'selected_with_documented_contributions':sum(bool(r['contributions']) for r in candidates),
        'publication_retrieval_status':'NOT_ATTEMPTED in directory pass',
        'external_author_verification_status':'PENDING; known conflicts excluded',
        'live_database_changed':False,
    }
    write_json(root/'FINAL_DIRECTORY_NUMBERS.json',numbers)
    lines=['# Faculty directory extraction: numbers','',
        'VIT Vellore only. SCOPE and SCORE. Faculty only. Directory extraction completed 19 October 2026.','',
        f"**{len(candidates)} selected faculty directory candidates.** These have extractable official identity, designation, qualifications, research interests and an ORCID or Scholar link. External-author verification and publication retrieval are subsequent stages; these are not publication-ready totals.",'',
        '| School | Faculty |','|---|---:|']
    lines += [f'| {s} | {n} |' for s,n in sorted(school.items())]
    lines += ['', '| School | Department | Faculty |','|---|---|---:|']
    lines += [f'| {s} | {d} | {n} |' for (s,d),n in sorted(depts.items())]
    lines += ['',f"Extracted official profiles: {len(extracted)} responses ({report['distinct_canonical_profiles']} distinct canonical URLs). Checked {len(updated)} listed profile links. Held {len(held)} distinct source profiles internally. PhD scholars and undergraduates excluded.",'',
              'No new records have been imported into the live app. This is a selected directory, not a complete faculty headcount. No external-author matches or publication histories are claimed verified by this pass.','']
    (root/'FINAL_DIRECTORY_NUMBERS.md').write_text('\n'.join(lines))
    print(json.dumps(numbers,indent=2))


if __name__=='__main__':main()
