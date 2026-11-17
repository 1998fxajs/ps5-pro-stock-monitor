"""One checked delivery path for production and the live notification test."""
import json
import os
import urllib.parse
import urllib.request
import monitor_window

def telegram(message):
    if not monitor_window.is_active_at():
        raise RuntimeError('Monitoring window ended; notification not sent')
    if os.environ.get('MONITOR_DRY_RUN') == '1':
        print('DRY RUN alert: '+message.replace('\n',' | ')[:900], flush=True)
        return {'dry_run': True}
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise RuntimeError('Telegram secrets missing')
    payload = urllib.parse.urlencode({'chat_id':chat,'text':message[:4000],
                                      'disable_web_page_preview':'false'}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',data=payload)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.load(response)
    except Exception as exc:
        # Exception strings from HTTP clients can contain the token-bearing URL.
        raise RuntimeError('Telegram transport failed: '+type(exc).__name__) from None
    if result.get('ok') is not True or not result.get('result',{}).get('message_id'):
        raise RuntimeError('Telegram did not acknowledge a message')
    receipt = {k:result['result'][k] for k in ('message_id','date') if k in result['result']}
    print('Telegram API accepted '+json.dumps(receipt), flush=True)
    return receipt
