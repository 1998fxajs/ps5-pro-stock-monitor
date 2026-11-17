"""Read-only context audit. Never imports notification or writes seen state."""
import concurrent.futures
from datetime import datetime, timedelta
import json
from pathlib import Path
import dcinside_watch as dc
import sale_link_review as s

def audit(row):
    title,url=row
    try:
        lead=s.inspect(title,url)
        return {'title':title,'url':url,'decision':'lead' if lead else 'reject',
                'lead':lead}
    except Exception as exc:return {'title':title,'url':url,'decision':'pending','error':str(exc)}

def main():
    url='https://gall.dcinside.com/mgallery/board/lists/?id=ps5'
    html=s.fetch_public(url);posts=dc.parse_posts(html,'ps5',url);dates=dc.post_dates(html)
    now=datetime.now(s.KST)
    current=[posts[k] for k in posts if k in dates and now-dates[k]<timedelta(hours=3)]
    historical=[('프로 풀렸다','728242'),('방금 뜬 프로','728331'),('취소분 샀다','728339'),('나도 이제야 샀다','728347')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        live=list(pool.map(audit,current[:60]))
        replay=list(pool.map(audit,[(t,'https://gall.dcinside.com/mgallery/board/view/?id=ps5&no='+n) for t,n in historical]))
    report={'at':now.isoformat(),'current':live,'historical':replay,
            'current_leads':[r['title'] for r in live if r['decision']=='lead'],
            'current_pending':sum(r['decision']=='pending' for r in live)}
    Path('context-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CONTEXT SUMMARY '+json.dumps({k:v for k,v in report.items() if k not in ('current','historical')},ensure_ascii=False))
    for row in replay:
        lead=row.get('lead') or {}
        print('HISTORICAL '+json.dumps({'url':row['url'],'decision':row['decision'],
            'image_text':lead.get('image_text'),'warnings':lead.get('warnings'),'error':row.get('error')},ensure_ascii=False))
    # 728347 was manually inspected: a game purchase, not a PS5 Pro console.
    if any(r['decision']!='lead' or not (r.get('lead') or {}).get('image_text','').strip() for r in replay[:3]):
        raise RuntimeError('Historical console image OCR needs review')
    if replay[3]['decision']!='reject':raise RuntimeError('Unrelated purchase photo was accepted')

if __name__=='__main__':main()
