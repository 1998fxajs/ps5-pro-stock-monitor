"""Public web results and deal pages, independent of Google News indexing.

Discovery sources are in source_registry.json. Related results are opened before
judgment. Uncertain leads are delivered, not suppressed by a price/title gate.
"""
import base64
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.parse
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from datetime import datetime
import monitor_window
import sale_link_review as review
from promo_watch import github, request, telegram

STATE = 'web_seen.json'
SOURCES = json.loads(Path(__file__).with_name('source_registry.json').read_text(encoding='utf-8'))['discovery']

def read_source(source):
    raw = request(source['url'])
    if source['type'] == 'rss':
        root = ET.fromstring(raw)
        return [{'title':i.findtext('title',''), 'link':i.findtext('link',''),
                 'description':i.findtext('description',''), 'source':source['label']}
                for i in root.findall('.//channel/item') if i.findtext('link','')]
    page = review.Article()
    page.feed(raw.decode('utf-8',errors='replace'))
    items = {}
    for href,label in page.links:
        url = urllib.parse.urljoin(source['url'],href)
        p = urllib.parse.urlparse(url)
        # Deal search results: read related result pages, not navigation or ads.
        if p.hostname != 'hotdeal.zip' or any(p.path.startswith(v) for v in ('/search/','/category','/tag/','/login','/buy','/privacy')):
            continue
        if not review.PLATFORM.search(label+' '+urllib.parse.unquote(p.path)):
            continue
        items[url] = {'title':label.strip(),'link':url,'description':'','source':source['label']}
    if not items:
        raise RuntimeError('No recognizable deal result links')
    return list(items.values())

def load():
    try:
        result=github('contents/'+STATE)
        return json.loads(base64.b64decode(result['content']).decode()),result['sha']
    except HTTPError as exc:
        if exc.code==404:
            return {'seen':[]},None
        raise

def save(state,sha):
    if __import__('os').environ.get('MONITOR_DRY_RUN')=='1':
        return
    payload={'message':'chore: record public web discovery',
             'content':base64.b64encode((json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode()).decode()}
    if sha:payload['sha']=sha
    github('contents/'+STATE,payload)

def main():
    if not monitor_window.is_active_at():return
    state,sha=load(); seen=set(state.get('seen',[])); items={}; failures=0; successes=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(read_source,s):s for s in SOURCES}
        for task in concurrent.futures.as_completed(tasks):
            source=tasks[task]
            try:
                rows=task.result();successes+=1
                print(f"WEB {source['label']}: {len(rows)} results")
                for row in rows:
                    key=hashlib.sha256(row['link'].encode()).hexdigest()[:24]
                    if key not in seen:items[key]=row
            except Exception as exc:
                failures+=1
                print(f"WEB {source['label']}: unavailable {type(exc).__name__}")
    sent=0; processed=[]; failed_alerts=[]
    # A backlog is left unseen; it is not silently marked delivered.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(review.inspect,row['title'],row['link'],row['description']):(key,row)
               for key,row in list(items.items())[:32]}
        for task in concurrent.futures.as_completed(tasks):
            key,row=tasks[task]
            try:
                lead=task.result()
                if lead:
                    telegram(review.format_alert(lead,row['source'],None));sent+=1
                processed.append(key)
            except Exception as exc:
                failed_alerts.append(key)
                print('WEB alert retained for retry: '+type(exc).__name__)
    if processed or sha is None:
        state['seen']=list(dict.fromkeys(state.get('seen',[])+processed))[-4000:]
        state['last_scan']={'at':datetime.now(review.KST).isoformat(),'sources_ok':successes,
                            'sources_failed':failures,'results':len(items),'alerts':sent,
                            'deferred':max(0,len(items)-32),'failed_alerts':len(failed_alerts)}
        save(state,sha)
    print('WEB '+json.dumps(state.get('last_scan',{})))
    if not successes or failed_alerts:raise RuntimeError('Web discovery or delivery failed')

if __name__=='__main__':main()
