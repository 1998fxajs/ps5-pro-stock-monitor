#!/usr/bin/env python3
"""Public PS5 Pro retailer page checks.

Strictly informational. Does not sign in, reserve inventory or buy.
A 'candidate' alert is only an indication that a product-specific sold-out
marker disappeared; it is NOT confirmed available stock.
"""
import base64
from notifications import telegram
import monitor_window
import sale_link_review
import marketplace_stock
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
        "id": "gmarket_playshop",
        "name": "지마켓 PlayShop / 오진상사 (공식 인증점)",
        "url": "https://item.gmarket.co.kr/Item?goodscode=4146068876",
        "type": "gmarket",
        "product_id": "4146068876",
        "seller_id": "ojintest",
        "title": r"(?:PS\s*5|PlayStation\s*5|플레이스테이션\s*5)\s*(?:Pro|프로)",
        "official_source": "https://www.playstation.com/ko-kr/local/retailers-list/",
    },
    {
        "id": "naver_playshop",
        "name": "네이버 PlayShop / 오진상사 (공식 인증점)",
        "url": "https://brand.naver.com/playshop/products/10897976014",
        "catalogue_url": "https://brand.naver.com/playshop/category/573e641896a64ee9a94ef552b6df37d4?cp=1",
        "type": "naver",
        "product_id": "10897976014",
        "channel_id": "100217750",
        "title": r"(?:PS\s*5|PlayStation\s*5|플레이스테이션\s*5)\s*(?:Pro|프로)",
        "official_source": "https://www.playstation.com/ko-kr/local/retailers-list/",
    },
    {
        "id": "coupang_reported",
        "name": "쿠팡 (커뮤니티에서 발견한 프로 + 듀얼센스 상품)",
        "url": "https://www.coupang.com/vp/products/9804453589?vendorItemId=96272680080",
        "type": "generic",
        "title": r"(?:플레이스테이션\s*5\s*프로|PS\s*5\s*Pro)",
    },
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
        "alternate_urls": [
            "https://m.ssg.com/item/itemView.ssg?itemId=1000619325394",
            "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1000619325394",
            "https://www.ssg.com/item/itemView.ssg?itemId=1000619325394",
        ],
        "type": "ssg",
        "title": r"(?:플레이스테이션\s*5\s*프로|PS\s*5\s*Pro)",
    },
    {
        "id": "compuzone",
        "name": "컴퓨존",
        "url": "https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1315525",
        "type": "compuzone",
        "title": r"PlayStation\s*5\s*Pro\s*콘솔",
    },
    {
        "id": "getthese",
        "name": "겟디즈 / THESE",
        "url": "https://get-these.com/product/ps5-pro-%EC%BD%98%EC%86%94-2tb-%EC%88%9C%EC%B0%A8%EC%B6%9C%EA%B3%A0/426/category/23/display/1/",
        "type": "cafe24",
        "title": r"PS5\s*Pro\s*콘솔\s*[-–]?\s*2TB(?:\s*순차출고)?",
    },
]

def fetch(url, data=None, headers=None, method=None):
    if not monitor_window.is_active_at() and not url.startswith('https://api.github.com/'):
        raise RuntimeError('Monitoring window ended')
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PS5ProWatch/1.0; public retail page)",
        "Accept": "text/html,application/json",
    } | (headers or {})
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
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
            if not sale_link_review.console_subject(name,False) or re.search(r"중고|리퍼|해외직구", name, re.I):
                continue
            price = price_of(offer.get("price"))
            currency = str(offer.get("priceCurrency", "")).upper()
            availability = str(offer.get("availability", "")).lower().split("/")[-1]
            if availability in ("outofstock", "soldout", "discontinued"):
                return {"status": "out_of_stock", "reason": "structured offer says out of stock"}
            if availability == "instock" and currency == "KRW" and price is not None:
                # GetThese's structured Offer availability has previously
                # flipped from InStock to OutOfStock within 15 minutes. It
                # does not independently prove the checkout accepts orders.
                # Do not label this unconfirmed schema signal as real stock.
                if store["id"] == "getthese" or price > PRICE_CEILING:
                    return {"status": "stock_signal",
                            "reason": "structured Offer=InStock; checkout/price/composition need confirmation",
                            "price": price,"product_name":name,"above_standalone_price":price>PRICE_CEILING}
                return {"status": "in_stock", "reason": "explicit product offer says InStock", "price": price,"product_name":name}
    return None

def parse_product(store, html):
    if store['type'] == 'gmarket':
        return marketplace_stock.gmarket(store, html)
    if store['type'] == 'naver':
        return marketplace_stock.naver(store, html)
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
    if store['type'] == 'naver':
        try:
            direct = parse_product(store, fetch(store['url']))
            direct['http_status'] = 200
        except Exception as exc:
            direct = error_result(exc)
        direct['checked_url'] = store['url']
        direct['direct_status'] = direct['status']
        if direct['status'] not in ('access_denied', 'unavailable', 'unknown'):
            return direct
        # The store's ordinary public console catalogue independently exposes
        # this exact item ID. This does not make the blocked direct check pass.
        # No alternate identity, proxy, login, hidden API or protection bypass.
        try:
            listing = marketplace_stock.naver(store, fetch(store['catalogue_url']), catalogue=True)
            if listing['status'] != 'unknown':
                listing.update(checked_url=store['catalogue_url'], http_status=200,
                               direct_status=direct['status'],
                               direct_http_status=direct.get('http_status'),
                               direct_reason=direct['reason'])
                return listing
            direct['catalogue_reason'] = listing['reason']
        except Exception as exc:
            direct['catalogue_reason'] = error_result(exc)['reason']
        return direct
    if store["type"] != "ssg":
        return dict(parse_product(store, fetch(store["url"])),
                    http_status=200, checked_url=store['url'])
    # Each of these are SSG's ordinary public product-page URLs for the
    # same verified item ID. No login, CAPTCHA, proxy, or protection bypass.
    failures = []
    unknowns = []
    for url in [store["url"]] + store.get("alternate_urls", []):
        try:
            html = fetch(url)
            result = parse_product(store, html)
            print(f"SSG PUBLIC PAGE: {url.split('/')[2]} HTTP 200, bytes={len(html)}, parsed={result['status']}")
            if result["status"] != "unknown":
                result["checked_url"] = url
                return result
            unknowns.append(result["reason"])
        except HTTPError as exc:
            failures.append(f"{url.split('/')[2]} HTTP {exc.code}")
        except Exception as exc:
            failures.append(f"{url.split('/')[2]} {type(exc).__name__}")
    # HTTP 200 with a tiny interstitial lacking the product title is not
    # useful stock data. Mark the source as inaccessible, not as "sold out".
    if failures and all("HTTP 403" in detail for detail in failures) and unknowns:
        status = "access_denied"
    elif failures and not unknowns:
        status = "access_denied"
    else:
        status = "unknown"
    return {"status": status,
            "reason": "All SSG public page variants lacked verified stock signal: " +
                      "; ".join((unknowns + failures)[:8])}


def error_result(exc):
    if isinstance(exc, HTTPError):
        return {'status': 'access_denied' if exc.code in (401, 403, 429) else 'unavailable',
                'http_status': exc.code,
                'reason': f'public HTTP request returned {exc.code}; direct stock check unavailable'}
    return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: public page read failed'}


def check_public(store):
    """Shared live-check path for the monitor and read-only validation."""
    try:
        return check(store)
    except Exception as exc:
        return dict(error_result(exc), checked_url=store['url'])

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
    return json.loads(fetch(f"https://api.github.com/repos/{repo}/{path}", payload_bytes, headers,
                            method="PUT" if payload is not None else "GET"))

def load_state():
    try:
        data = gh(f"contents/{STATE}")
        return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]
    except HTTPError as error:
        if error.code == 404:
            return {}, None
        raise

def save_state(data, sha):
    if os.environ.get('MONITOR_DRY_RUN') == '1':
        print('DRY RUN: retailer state not saved')
        return
    content = base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode()).decode()
    payload = {"message": "chore: record retailer state transitions", "content": content}
    if sha:
        payload["sha"] = sha
    gh(f"contents/{STATE}", payload)

def main():
    if not monitor_window.is_active_at():
        print("Watch ended at 2026-11-19 23:59 KST; no retailer checks or Telegram alerts")
        return
    state, sha = load_state()
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check_public, site): site for site in STORES}
        for future in concurrent.futures.as_completed(futures):
            site = futures[future]
            try:
                results[site["id"]] = (site, future.result())
            except HTTPError as exc:
                # A direct 403 can indicate automated-access restrictions, but
                # it may also be a network policy or temporary response.
                # Do not try to defeat login, CAPTCHA or bot protections.
                status = "access_denied" if exc.code in (401, 403, 429) else "unavailable"
                results[site["id"]] = (site, {
                    "status": status,
                    "reason": f"public HTTP request returned {exc.code}; direct stock check unavailable"
                })
                print(f"{site['name']}: HTTP {exc.code} ({status})", file=sys.stderr)
            except Exception as exc:
                results[site["id"]] = (site, {
                    "status": "unavailable",
                    "reason": f"{type(exc).__name__}: {str(exc)[:120]}"
                })
                print(f"{site['name']}: check failed ({type(exc).__name__}: {exc})", file=sys.stderr)
    if not results:
        raise RuntimeError("No retailer check produced a state")
    changed = False
    for key, (site, result) in results.items():
        previous = state.get(key, {}).get("status")
        current = result["status"]
        print(json.dumps({"store": site["name"], **result}, ensure_ascii=False))
        if current == "in_stock" and previous != "in_stock":
            telegram(
                f"[PS5 Pro 본체 포함 상품 재고 표기 — 확인 필요]\n"
                f"{site['name']} | {result['price']:,}원\n"
                f"상품: {result.get('product_name','상품명 확인 필요')}\n"
                f"{site['url']}\n"
                "판매처 재고 표기이며 실제 결제 가능 여부와 포함 구성은 확인하세요."
            )
        elif current == "stock_signal" and previous != "stock_signal":
            telegram(
                "[PS5 Pro 재고 표기 변동 — 실제 구매 가능 여부 미확인]\n"
                f"{site['name']} | 사이트 표기 {result['price']:,}원\n"
                f"상품: {result.get('product_name','상품명 확인 필요')}\n"
                f"{site['url']}\n"
                +( "기존 단품 희망가격 초과 — 포함 구성과 가격 확인 필요\n" if result.get('above_standalone_price') else "")+
                "판매처의 공개 상품 데이터에서 판매 가능 표기가 확인됐지만 "
                "실제 주문 가능 여부는 확인되지 않았습니다. "
                "품절로 표시될 수도 있으니 상품 페이지를 확인하세요."
            )
        elif current == 'raffle_signal' and previous != 'raffle_signal':
            telegram(
                '[PS5 Pro 공식 추첨 상품 표시 변경 — 일반 구매 재고 아님]\n'
                f"{site['name']}\n상품: {result['product_name']}\n{site['url']}\n"
                '추첨 상품의 품절 표기가 해제됐습니다. 응모 기간과 조건을 확인하세요. '
                '응모용 표시 가격을 본체 판매가격으로 취급하지 않습니다.'
            )
        elif current == "access_denied" and previous != "access_denied":
            telegram(
                "[PS5 Pro 감시 장애 - 접근 제한 가능성]\n"
                f"{site['name']}\n{site['url']}\n"
                "GitHub 실행 환경에서 사이트가 401/403/429를 반환했습니다. "
                "재고 없음이 아니라 직접 확인 불가입니다. "
                "공개 판매글 탐색은 별도 실행됩니다."
            )
        elif previous == "out_of_stock" and current == "unknown" and site["type"] == "cafe24":
            # Potentially relevant *change* only; intentionally not called stock.
            telegram(
                f"[PS5 Pro 품절 표시 변경 — 확인 필요]\n"
                f"{site['name']}\n{site['url']}\n"
                "품절 표시를 기존처럼 확인할 수 없습니다. 구매 가능 재고 확정이 아닙니다."
            )
        previous_direct = state.get(key, {}).get('direct_status')
        direct_failures = ('access_denied', 'unavailable', 'unknown')
        if (result.get('direct_status') in direct_failures and current not in direct_failures
                and previous_direct not in direct_failures):
            telegram(
                '[PS5 Pro 직접 감시 일부 제한 — 공식 목록 보조 확인]\n'
                f"{site['name']}\n{site['url']}\n"
                f"개별 상품 HTTP {result.get('direct_http_status')}: 직접 재고 확인 불가.\n"
                f"동일 상품 ID의 공식 콘솔 목록 상태: {current}\n"
                f"보조 확인: {result['checked_url']}"
            )
        if current != previous or result.get('direct_status') != previous_direct:
            changed = True
        state[key] = {**result, 'checked_at': datetime.now(timezone.utc).isoformat()}
    state['_last_scan'] = {'checked_at': datetime.now(timezone.utc).isoformat(),
                           'stores_checked': len(results)}
    save_state(state, sha)
    print(f"Retail check complete: {len(results)} shops; state changed={changed}")

if __name__ == "__main__":
    main()
