#!/usr/bin/env python3
"""Public PS5 Pro retailer page checks.

Strictly informational. Does not sign in, reserve inventory or buy.
A 'candidate' alert is only an indication that a product-specific sold-out
marker disappeared; it is NOT confirmed available stock.
"""
import base64
import concurrent.futures
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode

STATE = "retail_state.json"
PRICE_CEILING = 1_298_000
STORES = [
    {
        "id": "gamewoori",
        "name": "겜우리 (인증판매점)",
        "url": "https://www.gamewoori.com/product/detail.html?product_no=16602",
        "type": "cafe24",
        "title": r"PlayStation\s*5\s*프로\s*본체\s*2TB\s*CFI[-\s]*7122B",
    },
    {
        "id": "ssg_emart",
        "name": "이마트몰 / SSG",
        "url": "https://emart.ssg.com/item/itemDtl.ssg?itemId=1000619325394",
        "type": "ssg",
        "title": r"플레이스테이션\s*5\s*프로",
    },
    {
        "id": "compuzone",
        "name": "컴퓨존",
        "url": "https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1315525",
        "type": "compuzone",
        "title": r"PlayStation\s*5\s*Pro\s*콘솔",
    },
]

def fetch(url, data=None, headers=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PS5ProWatch/1.0; public retail page)",
        "Accept": "text/html,application/json",
    } | (headers or {})
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=19) as response:
        content = response.read()
        charset = response.headers.get_content_charset()
    if not charset:
        head = content[:4096].decode("latin-1")
        match = re.search(r'<meta[^>]+charset\s*=\s*["\']?([a-z0-9_-]+)', head, re.I)
        charset = match.group(1) if match else "utf-8"
    return content.decode(charset, errors="replace")

def clean_text(raw):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", raw))).strip()

class StructuredScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_jsonld = False
        self.scripts = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.in_jsonld = True
            self.scripts.append("")
    def handle_endtag(self, tag):
        if tag == "script":
            self.in_jsonld = False
    def handle_data(self, data):
        if self.in_jsonld and self.scripts:
            self.scripts[-1] += data

def offers(node):
    if isinstance(node, list):
        for child in node:
            yield from offers(child)
    elif isinstance(node, dict):
        types = node.get("@type", "")
        is_product = types == "Product" or isinstance(types, list) and "Product" in types
        if is_product:
            offers_field = node.get("offers", [])
            if isinstance(offers_field, dict):
                offers_field = [offers_field]
            if isinstance(offers_field, list):
                for offer in offers_field:
                    if isinstance(offer, dict):
                        yield node, offer
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from offers(child)

def price_of(raw):
    if isinstance(raw, (int, float)):
        return int(raw) if 0 < raw < 100000000 else None
    digits = re.sub(r"[,\s]", "", str(raw))
    return int(digits) if re.fullmatch(r"\d{5,8}", digits) else None

def structured_status(html, store):
    parser = StructuredScripts()
    parser.feed(html)
    for source in parser.scripts:
        try:
            data = json.loads(unescape(source))
        except (json.JSONDecodeError, TypeError):
            continue
        for product, offer in offers(data):
            name = clean_text(str(product.get("name", "")))
            if not re.search(store["title"], name, re.I):
                continue
            if re.search(r"디스크\s*드라이브\s*\+|세트|번들|중고|리퍼|해외직구", name, re.I):
                continue
            price = price_of(offer.get("price"))
            currency = str(offer.get("priceCurrency", "")).upper()
            availability = str(offer.get("availability", "")).lower().split("/")[-1]
            if availability in ("outofstock", "soldout", "discontinued"):
                return {"status": "out_of_stock", "reason": "structured offer says out of stock"}
            if availability == "instock" and currency == "KRW" and price is not None and price <= PRICE_CEILING:
                return {"status": "in_stock", "reason": "explicit product offer says InStock", "price": price}
            if availability == "instock" and currency == "KRW" and price is not None and price > PRICE_CEILING:
                return {"status": "over_budget", "reason": "explicit offer above standalone ceiling", "price": price}
    return None

def parse_product(store, html):
    text = clean_text(html)
    if not re.search(store["title"], text, re.I):
        return {"status": "unknown", "reason": "expected product title absent"}

    # Require sold-out marker in the product heading, not arbitrary page text
    # or a carousel of unrelated goods. Cafe24 typically embeds this in h1/h2.
    if store["type"] == "cafe24":
        headings = re.findall(r"<h[1-3]\b[^>]*>.*?</h[1-3]>", html, re.I | re.S)
        for heading in headings:
            if (re.search(store["title"], clean_text(heading), re.I)
                    and re.search(r"<img\b[^>]*\balt\s*=\s*['\"]품절['\"]", heading, re.I)):
                return {"status": "out_of_stock", "reason": "product-heading sold out badge"}
        # Some Cafe24 themes place a SOLD OUT button inside the purchase UI,
        # but pages can contain 'SOLD OUT' in unrelated recommendations, so
        # this is not used as a positive signal.
    elif store["type"] == "ssg":
        if re.search(r"sellStatCd\s*=\s*80", html, re.I):
            return {"status": "out_of_stock", "reason": "SSG sellStatCd=80"}
    elif store["type"] == "compuzone":
        # '구매하기' appears on pages even when '입고예정: 미정' is shown.
        # Its presence alone is NOT an in-stock signal.
        if re.search(r"입고예정\s*</?[^>]*>?\s*미정", html):
            return {"status": "out_of_stock", "reason": "replenishment ETA unknown"}

    positive = structured_status(html, store)
    if positive is not None:
        return positive
    return {"status": "unknown", "reason": "no validated explicit product-level in-stock signal"}

def check(store):
    return parse_product(store, fetch(store["url"]))

def gh(path, payload=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload_bytes = json.dumps(payload).encode() if payload is not None else None
    return json.loads(fetch(f"https://api.github.com/repos/{repo}/{path}", payload_bytes, headers))

def load_state():
    try:
        data = gh(f"contents/{STATE}")
        return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]
    except HTTPError as error:
        if error.code == 404:
            return {}, None
        raise

def save_state(data, sha):
    content = base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode()).decode()
    payload = {"message": "chore: record retailer state transitions", "content": content}
    if sha:
        payload["sha"] = sha
    gh(f"contents/{STATE}", payload)

def telegram(message):
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat_id:
        raise RuntimeError("Telegram secrets missing")
    data = urlencode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}).encode()
    response = json.loads(fetch(
        f"https://api.telegram.org/bot{bot}/sendMessage", data,
        {"Content-Type": "application/x-www-form-urlencoded"}))
    if not response.get("ok"):
        raise RuntimeError("Telegram did not confirm delivery")

def main():
    state, sha = load_state()
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(check, site): site for site in STORES}
        for future in concurrent.futures.as_completed(futures):
            site = futures[future]
            try:
                results[site["id"]] = (site, future.result())
            except Exception as exc:
                print(f"{site['name']}: check failed ({type(exc).__name__}: {exc})", file=sys.stderr)
    if not results:
        raise RuntimeError("Every retailer check failed")
    changed = False
    for key, (site, result) in results.items():
        previous = state.get(key, {}).get("status")
        current = result["status"]
        print(json.dumps({"store": site["name"], **result}, ensure_ascii=False))
        if current == "in_stock" and previous != "in_stock":
            telegram(
                f"[PS5 Pro 2TB 단품 재고 감지]\n"
                f"{site['name']} | {result['price']:,}원\n"
                f"{site['url']}\n"
                "결제 가능 여부와 단품 구성은 최종 확인하세요."
            )
        elif previous == "out_of_stock" and current == "unknown" and site["type"] == "cafe24":
            # Potentially relevant *change* only; intentionally not called stock.
            telegram(
                f"[PS5 Pro 품절 표시 변경 — 확인 필요]\n"
                f"{site['name']}\n{site['url']}\n"
                "품절 표시를 기존처럼 확인할 수 없습니다. 구매 가능 재고 확정이 아닙니다."
            )
        if current != previous:
            state[key] = {
                "status": current,
                "reason": result["reason"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
    if changed:
        save_state(state, sha)
    print(f"Retail check complete: {len(results)} shops; state changed={changed}")

if __name__ == "__main__":
    main()
