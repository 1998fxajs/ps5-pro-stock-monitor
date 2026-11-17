"""Read-only live source smoke check. Exactly one clearly labelled Telegram test.

Does not write monitoring state or claim the historical sample is a live sale.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import urllib.request
import monitor_window
import dcinside_watch as dc
import sale_link_review as review
import web_discovery as web
from notifications import telegram

def main():
    if not monitor_window.is_active_at():
        print('Expired: no live requests or tests');return
    summary={'sources':[],'replay':[]}
    for label,board,url in dc.GALLERIES:
        try:
            html=dc.request(url).decode('utf-8',errors='replace')
            posts=dc.parse_posts(html,board,url)
            row={'source':label,'posts':len(posts),'usable_titles':sum(not t[0].startswith('[') or len(t[0])>5 for t in posts.values())}
        except Exception as exc:row={'source':label,'error':type(exc).__name__}
        summary['sources'].append(row);print(json.dumps(row,ensure_ascii=False))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(web.read_source,s):s for s in web.SOURCES}
        for task in concurrent.futures.as_completed(tasks):
            try:row={'source':tasks[task]['label'],'results':len(task.result())}
            except Exception as exc:row={'source':tasks[task]['label'],'error':type(exc).__name__}
            summary['sources'].append(row);print(json.dumps(row,ensure_ascii=False))
    sample_url='https://gall.dcinside.com/mgallery/board/view/?id=ps5&no=728242'
    lead=review.inspect('프로 풀렸다',sample_url)
    if not lead:raise RuntimeError('Historical missed example did not produce a lead')
    summary['replay'].append({'id':'728242','body':lead['reviewed_body'],'images':len(lead['images'])})
    if os.environ.get('SEND_TEST_ALERT')=='1':
        message=('[테스트 · 과거 글 재현 — 현재 재고 알림 아님]\n'
                 '11/16 누락 글을 본문·사진 포함 알림 경로로 재현했습니다.\n'
                 +review.format_alert(lead,'테스트용 과거 디시 글',None))
        summary['telegram_receipt']=telegram(message)
    Path('validation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('## Live validation\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n')
    if any(row.get('error') for row in summary['sources']):
        raise RuntimeError('Some sources failed: see per-source report')

if __name__=='__main__':main()
