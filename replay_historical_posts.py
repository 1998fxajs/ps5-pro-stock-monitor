"""Re-read the actual 11/16 23:00 hour; optionally send labelled past alerts.

Uses production body/link/OCR review and Telegram delivery. Never reads or
writes seen/state files. No production stock is inferred from old receipts.
"""
import concurrent.futures
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import image_ocr
import monitor_window
import sale_link_review as review
from notifications import telegram

MANIFEST = Path(__file__).with_name('historical_replay_20261116_23.json')
REPORT = Path('historical-replay-report.json')


def audit(row):
    fetched = {}
    images = []

    def fetch(url):
        html = review.fetch_public(url)
        fetched[url] = html
        return html

    def ocr(url, referer):
        raw = review.fetch_public(url, referer=referer, binary=True)
        text, status = image_ocr.recognize(raw)
        images.append({'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                       'status': status, 'console_identified': review.console_subject(text, False),
                       'receipt_markers': bool(review.RECEIPT_IMAGE.search(text)),
                       'product_excerpt': review.product_excerpt(text)})
        return text, status

    result = dict(row)
    lead = None
    try:
        lead = review.inspect(row['title'], row['url'], now=datetime.fromisoformat(row['published']),
                              fetcher=fetch, ocr=ocr)
        result['decision'] = 'lead' if lead else 'reject'
        result['basis'] = lead.get('decision_basis') if lead else row['review_category']
    except Exception as exc:
        result.update(decision='pending', error=str(exc))
    html = fetched.get(row['url'])
    result['body_fetched'] = html is not None
    if html is not None:
        body, _ = review.post_content.extract(html, row['url'])
        result['html_sha256'] = hashlib.sha256(html.encode()).hexdigest()
        result['body_excerpt'] = ' '.join(review.plain(body).split()[:20])[:180]
    result['image_reads'] = images
    result['matches_review'] = result['decision'] == row['expected']
    return result, lead


def write_report(report):
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    if not monitor_window.is_active_at():
        raise RuntimeError('Monitoring window ended; no historical messages sent')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        audited = list(pool.map(audit, manifest['posts']))
    report = {'window_kst': manifest['window_kst'], 'notes': manifest['notes'],
              're_read_at': datetime.now(review.KST).isoformat(),
              'code_commit': os.environ.get('GITHUB_SHA'),
              'posts': [row for row, _ in audited], 'telegram_receipts': []}
    mismatches = [r for r, _ in audited if not r['matches_review']]
    report['mismatches'] = [r['id'] for r in mismatches]
    report['accepted'] = [r['id'] for r, _ in audited if r['decision'] == 'lead']
    write_report(report)
    for row, _ in audited:
        print('ACTUAL POST '+json.dumps({k:row[k] for k in ('id','title','published','decision','review_category','matches_review','body_fetched')}, ensure_ascii=False), flush=True)
    if mismatches:
        print('REPLAY MISMATCH '+json.dumps(mismatches, ensure_ascii=False), flush=True)
        raise RuntimeError('Actual source review mismatch or inaccessible post; no test alerts sent')
    # A title alone does not stand in for reading the relevant product photo.
    photo = next(r for r, _ in audited if r['id'] == '728242')
    if not any(i['status'] == 'OCR read' and i['console_identified'] for i in photo['image_reads']):
        raise RuntimeError('Actual restock photo was not read; no test alerts sent')
    if os.environ.get('SEND_HISTORICAL_TEST') == '1':
        leads = [(r, lead) for r, lead in audited if lead is not None]
        for index, (row, lead) in enumerate(leads, 1):
            message = (f'[과거 글 검증 {index}/{len(leads)} · 현재 재고 알림 아님]\n'
                       '대상: 2026-11-16 23:00~23:59 KST\n'
                       '아래 글이 올라온 당시의 재고 제보를 재현한 테스트입니다.\n\n'
                       +review.format_alert(lead, '디시 PS5 · 과거 재현', datetime.fromisoformat(row['published'])))
            receipt = telegram(message)
            report['telegram_receipts'].append({'post_id': row['id'], **receipt})
            write_report(report)
    summary = {'window_kst': report['window_kst'], 'actual_posts_read': len(audited),
               'accepted': report['accepted'], 'mismatches': report['mismatches'],
               'telegram_receipts': report['telegram_receipts']}
    print('REPLAY SUMMARY '+json.dumps(summary, ensure_ascii=False), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write('## Actual historical post replay\n```json\n'+json.dumps(summary, ensure_ascii=False, indent=2)+'\n```\n')


if __name__ == '__main__':
    main()
