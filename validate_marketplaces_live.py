"""Read real public pages and send one labelled test via production delivery.

Does not load or save retail_state/seen files. Reports blocked sources honestly;
successful Telegram delivery does not mean every source is readable.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import monitor_window
import retail_watch
from notifications import telegram

TARGETS = {'gmarket_playshop', 'naver_playshop', 'coupang_reported'}


def main():
    if not monitor_window.is_active_at():
        print('Expired: no live check or test message')
        return
    summary = {'checked_at': datetime.now(timezone.utc).isoformat(),
               'sources': [], 'all_direct_pages_verified': True}
    for store in retail_watch.STORES:
        if store['id'] not in TARGETS:
            continue
        result = retail_watch.check_public(store)
        row = {'id': store['id'], 'name': store['name'], 'url': store['url'], **result}
        summary['sources'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if (result['status'] in ('access_denied', 'unavailable', 'unknown')
                or result.get('direct_status') in ('access_denied', 'unavailable', 'unknown')):
            summary['all_direct_pages_verified'] = False
    assert {s['id'] for s in summary['sources']} == TARGETS
    path = Path('marketplace-validation.json')
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if os.environ.get('SEND_TEST_ALERT') == '1':
        lines = ['[검증용 · PS5 Pro 직접 감시 — 재입고 알림 아님]',
                 '운영과 동일한 HTTP 검사·텔레그램 전송 경로의 실제 결과입니다.']
        labels = {'out_of_stock': '품절 표기', 'access_denied': '접근 제한',
                  'unavailable': '접속 실패', 'unknown': '판정 불가',
                  'stock_signal': '판매 가능 표기(구매 미확인)',
                  'in_stock': '재고 표기(구매 미확인)', 'raffle_signal': '추첨 상품 표시 변경'}
        for row in summary['sources']:
            lines.append(f"{row['name']}: {labels.get(row['status'], row['status'])}")
            if row.get('evidence_type') == 'official_catalogue':
                lines.append(f"  직접 상품 HTTP {row.get('direct_http_status')}: 판정 불가; 공식 목록의 동일 상품 ID만 보조 확인")
            elif row.get('http_status'):
                lines.append(f"  HTTP {row['http_status']}")
            if row.get('sale_mode') == 'raffle':
                lines.append('  현재 추첨응모 상품이며 일반 구매 재고가 아닙니다.')
            lines.append(row['url'])
        lines.append('실제 구매·결제는 수행하지 않았습니다. 차단을 품절로 처리하지 않습니다.')
        summary['telegram_receipt'] = telegram('\n'.join(lines))
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write('## Marketplace live observations\n```json\n'
                    +json.dumps(summary, ensure_ascii=False, indent=2)+'\n```\n')
    print(json.dumps({'all_direct_pages_verified': summary['all_direct_pages_verified'],
                      'telegram_receipt': summary.get('telegram_receipt')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
