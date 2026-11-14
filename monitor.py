#!/usr/bin/env python3
"""PS5 Pro monitor: conservative public-page checks; never purchases."""
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PRODUCT_URL = "https://playshop.co.kr/product/ps5-pro-%EC%BD%98%EC%86%94-2tb/334/category/29/display/1/"
CHECK_URLS = [
    PRODUCT_URL,
    "https://ojinplaystation.cafe24.com/product/ps5-pro-%EC%BD%98%EC%86%94/334/",
    "https://playshop.co.kr/product/detail.html?product_no=334",
]
PRICE_LIMIT = 1_298_000
STATE_FILE = "monitor_state.json"
USER_AGENT = "Mozilla/5.0 (compatible; PS5ProMonitor/1.0; public stock check)"

def http(url, data=None, headers=None):
    h = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    h.update(headers or {})
    req = Request(url, data=data, headers=h)
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")

def clean_price(value):
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None

def offers_from_json(obj):
    if isinstance(obj, list):
        for item in obj:
            yield from offers_from_json(item)
    if not isinstance(obj, dict):
        return
    if obj.get("@type") in ("Product", ["Product"]):
        for offer in (obj.get("offers", []) if isinstance(obj.get("offers", []), list) else [obj.get("offers", {})]):
            if isinstance(offer, dict):
                yield obj, offer
    for value in obj.values():
        if isinstance(value, (dict, list)):
            yield from offers_from_json(value)

class JsonLD(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.scripts = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.inside = True
            self.scripts.append("")
    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False
    def handle_data(self, data):
        if self.inside and self.scripts:
            self.scripts[-1] += data

def check_playshop(html):
    # Restrict to expected item; do not use generic page-wide '품절' or '구매' strings.
    if not re.search(r"PS5\s*Pro\s*콘솔\s*[-–]\s*2TB", html, re.IGNORECASE):
        return {"status": "unknown", "reason": "product title not verified"}
    # The current official page includes an image with alt='품절' next to its
    # product heading, which is a reliable *negative* inventory signal.
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if heading and re.search(r"<img\b[^>]*\balt\s*=\s*['\"]품절['\"]", heading.group(1), re.IGNORECASE):
        return {"status": "out_of_stock", "reason": "product heading sold-out image"}
    # Never infer availability from disappearance of the sold-out image.
    # Positive alert only when product-specific JSON-LD explicitly claims InStock
    # AND is a standalone product at the permitted price.
    parser = JsonLD()
    parser.feed(html)
    for data in parser.scripts:
        try:
            objects = json.loads(unescape(data))
        except (ValueError, TypeError):
            continue
        for product, offer in offers_from_json(objects):
            name = str(product.get("name", ""))
            if not re.fullmatch(r"\s*PS5\s*Pro\s*콘솔\s*[-–]\s*2TB\s*", name, re.IGNORECASE):
                continue
            availability = str(offer.get("availability", "")).lower().split("/")[-1]
            price = clean_price(offer.get("price", ""))
            currency = offer.get("priceCurrency", "KRW")
            if availability == "instock" and currency == "KRW" and price is not None and price <= PRICE_LIMIT:
                return {"status": "in_stock", "reason": "explicit structured product offer", "price": price}
            if availability in ("outofstock", "soldout"):
                return {"status": "out_of_stock", "reason": "structured offer out of stock"}
    return {"status": "unknown", "reason": "no verified positive availability signal"}

def gh(path, data=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"}
    payload = json.dumps(data).encode() if data is not None else None
    return json.loads(http(f"https://api.github.com/repos/{repo}/{path}", payload, headers))

def load_state():
    import base64
    try:
        response = gh(f"contents/{STATE_FILE}")
        return json.loads(base64.b64decode(response["content"]).decode()), response["sha"]
    except HTTPError as e:
        if e.code == 404:
            return {}, None
        raise

def save_state(state, sha):
    import base64
    payload = {
        "message": "chore: update stock state",
        "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    gh(f"contents/{STATE_FILE}", payload)

def alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError("Telegram Secrets are missing")
    data = urlencode({"chat_id": chat, "text": message, "disable_web_page_preview": "true"}).encode()
    resp = json.loads(http(f"https://api.telegram.org/bot{token}/sendMessage", data, {
        "Content-Type": "application/x-www-form-urlencoded"}))
    if not resp.get("ok"):
        raise RuntimeError("Telegram API did not confirm alert")

def main():
    html = None
    failed_urls = []
    for url in CHECK_URLS:
        try:
            html = http(url)
            break
        except HTTPError as exc:
            if exc.code not in (404, 410):
                raise
            failed_urls.append(f"{url}: HTTP {exc.code}")
    if html is None:
        result = {"status": "unavailable", "reason": "GitHub runner received 404/410 for every public PlayShop product URL"}
        print("PlayShop check inaccessible from GitHub runner; not treating as sold out")
    else:
        result = check_playshop(html)
    status = result["status"]
    previous, sha = load_state()
    before = previous.get("playshop", {}).get("status")
    print(json.dumps({"shop": "PlayShop", **result}, ensure_ascii=False))
    # Alert as soon as confirmed by this run; no additional 5-minute delay.
    # Notify on every confirmed-positive run until state is saved successfully.
    if status == "in_stock" and before != "in_stock":
        alert(f"PS5 Pro 2TB 단품 정가 재고 감지\n{result['price']:,}원\n{PRODUCT_URL}\n"
              "결제 가능 여부는 판매처에서 직접 확인하세요.")
    elif status == "unavailable" and before != "unavailable":
        alert("[감시 장애] PlayShop 상품 페이지가 GitHub 클라우드에서 404를 반환하여 "
              "직접 재고 확인이 불가능합니다. 다른 판매처 감시는 별도로 유지됩니다.\n" + PRODUCT_URL)
    if status != before:
        previous["playshop"] = {
            "status": status, "reason": result["reason"],
            "changed_at": datetime.now(timezone.utc).isoformat()
        }
        save_state(previous, sha)
    print(f"Check complete: {before} -> {status}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Monitor error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
