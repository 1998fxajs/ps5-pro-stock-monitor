#!/usr/bin/env python3
"""Conservative PS5 Pro stock monitor. No checkout or purchase automation."""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

STORE_URL = "https://playshop.co.kr/product/ps5-pro-%EC%BD%98%EC%86%94/334"
PRICE_LIMIT_KRW = 1298000
STATE_PATH = "monitor_state.json"
USER_AGENT = "Mozilla/5.0 (compatible; PS5ProAvailabilityMonitor/1.0)"

def request(url, data=None, headers=None, method=None):
    h = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    h.update(headers or {})
    req = Request(url, data=data, headers=h, method=method)
    with urlopen(req, timeout=18) as response:
        return response.read().decode("utf-8", errors="replace")

def check_playshop():
    """Fail closed: never infer buyability just because 'sold out' is absent."""
    html = request(STORE_URL)
    low = html.lower()
    if not re.search(r"(ps5\s*pro|ps5\s*프로)", html, re.IGNORECASE):
        return {"status": "unknown", "reason": "Product identity absent"}
    if "1298000" not in re.sub(r"[, ]", "", html):
        return {"status": "unknown", "reason": "Exact standalone list price not verified"}
    # Product-specific sold-out signal. This is intentionally conservative:
    # a site redesign is NOT a confirmed in-stock notification.
    if any(token in low for token in ("sold out", "soldout")) or "품절" in html:
        return {"status": "out_of_stock", "reason": "Sold-out marker found"}
    # A site-specific, validated in-stock signal has not yet been confirmed.
    return {"status": "unknown", "reason": "No verified in-stock indicator; manual review required"}

def github_api(path, data=None, method=None):
    repo = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY/GITHUB_TOKEN missing")
    url = f"https://api.github.com/repos/{repo}/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}
    payload = json.dumps(data).encode() if data is not None else None
    return json.loads(request(url, payload, headers, method)) if method != "DELETE" else {}

def load_state():
    try:
        import base64
        obj = github_api(f"contents/{STATE_PATH}")
        return json.loads(base64.b64decode(obj["content"]).decode()), obj["sha"]
    except HTTPError as e:
        if e.code == 404:
            return {}, None
        raise

def save_state(state, sha):
    import base64
    payload = {"message": "chore: record stock monitor transition",
               "content": base64.b64encode((json.dumps(state, indent=2, ensure_ascii=False)+"\n").encode()).decode()}
    if sha:
        payload["sha"] = sha
    github_api(f"contents/{STATE_PATH}", payload, "PUT")

def send_telegram(message):
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot or not chat:
        print("Telegram secrets not configured; alert cannot be delivered")
        return False
    from urllib.parse import urlencode
    data = urlencode({"chat_id": chat, "text": message, "disable_web_page_preview": "true"}).encode()
    response = json.loads(request(f"https://api.telegram.org/bot{bot}/sendMessage", data,
                                 {"Content-Type": "application/x-www-form-urlencoded"}, "POST"))
    return bool(response.get("ok"))

def main():
    try:
        finding = check_playshop()
        print(json.dumps({"store": "PlayShop", **finding}, ensure_ascii=False))
    except Exception as exc:
        print(f"PlayShop check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    previous, sha = load_state()
    status = finding["status"]
    old = previous.get("playshop", {}).get("status")
    now = datetime.now(timezone.utc).isoformat()
    # Only confirmed 'in_stock' may trigger an immediate stock notification.
    # An uncertain result never becomes an automated checkout event.
    if status == "in_stock" and old != "in_stock":
        message = f"PS5 Pro 2TB 단품 정가 재고 발견 (1,298,000원 이하)\nPlayShop\n{STORE_URL}"
        if not send_telegram(message):
            raise RuntimeError("Stock alert delivery failed; will retry")
    if status != old:
        previous["playshop"] = {"status": status, "changed_at": now, "reason": finding["reason"]}
        save_state(previous, sha)
    print(f"Monitor complete. State={status}; previous={old}")

if __name__ == "__main__":
    main()
