#!/usr/bin/env python3
"""Discover newly published PS5 Pro product URLs from public store listings.

New listing alerts are *leads*, not proof of stock or price.
Gmarket is deliberately excluded from direct store access.
"""
import base64
import concurrent.futures
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError

import monitor_window
from promo_watch import INCLUDE, EXCLUDE, telegram

STATE_PATH = "catalog_seen.json"
STORE_LISTS = [
    {
        "id": "gamewoori",
        "name": "겜우리 PS5 Pro 목록",
        "url": "https://gamewoori.com/category/pro/677/",
        "domain": "gamewoori.com",
        "path_key": "product",
        "type": "cafe24",
    },
    {
        "id": "getthese",
        "name": "겟디즈 상품 카테고리",
        "url": "https://get-these.com/category/product/23/",
        "alternate_urls": ["https://get-these.com/"],
        "domain": "get-these.com",
        "path_key": "product",
        "type": "cafe24",
    },
    {
        "id": "ssg",
        "name": "SSG / 이마트 새 판매 페이지",
        "url": "https://www.ssg.com/search.ssg?query=%ED%94%8C%EC%8A%A45%ED%94%84%EB%A1%9C",
        "alternate_urls": [
            "https://emart.ssg.com/search.ssg?query=%ED%94%8C%EC%8A%A45%ED%94%84%EB%A1%9C",
            "https://emart.ssg.com/disp/category.ssg?dispCtgId=6000214771",
            "https://m.department.ssg.com/disp/category.ssg?ctgId=6000209317",
        ],
        "domain": "ssg.com",
        "path_key": "item",
        "type": "ssg",
    },
    {
        "id": "compuzone",
        "name": "컴퓨존 상품 검색",
        "url": "https://www.compuzone.co.kr/product/product_list.htm?BigDivNo=103&DivNo=4044&MediumDivNo=1381",
        "alternate_urls": ["https://www.compuzone.co.kr/search/search.htm?Seargbl=1&SearchType=0&SearchProductKey=PS5%20Pro"],
        "domain": "compuzone.co.kr",
        "path_key": "product",
        "type": "compuzone",
    },
]
MAX_ALERTS = 8

def request(url, data=None, headers=None, method=None):
    h = {
        "User-Agent": "Mozilla/5.0 (compatible; PS5ProCatalogWatch/1.0)",
        "Accept": "text/html,application/json",
    }
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read()
        enc = response.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = []
    def handle_starttag(self, tag, attrs):
        att = dict(attrs)
        if tag == "a":
            self.stack.append({"href": att.get("href", ""), "text": []})
        elif tag == "img" and self.stack:
            self.stack[-1]["text"].extend([att.get("alt", ""), att.get("title", "")])
    def handle_data(self, data):
        if self.stack:
            self.stack[-1]["text"].append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.stack:
            item = self.stack.pop()
            if self.stack:
                self.stack[-1]["text"].extend(item["text"])
            self.found.append((item["href"], " ".join(item["text"])))

def acceptable_title(name):
    name = re.sub(r"\s+", " ", unescape(name)).strip()
    if not INCLUDE.search(name) or EXCLUDE.search(name):
        return False
    if re.search(r"(?:디스크\s*드라이브\s*\+|듀얼센스\s*\+|번들|묶음|세트|중고|리퍼|직구)", name, re.I):
        return False
    return True

def allow_url(url, source):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != source["domain"] and not host.endswith("." + source["domain"]):
        return False
    path = parsed.path.lower()
    if source["type"] == "cafe24":
        return "/product/" in path and (
            re.search(r"/\d+/?$", path) is not None or
            "product_no=" in parsed.query.lower() or
            re.search(r"/\d+/category/", path) is not None
        )
    if source["type"] == "ssg":
        return "itemview.ssg" in path or "itemdtl.ssg" in path
    return "product_detail.htm" in path and "productno=" in parsed.query.lower()

def discover(source, html):
    parser = Links()
    parser.feed(html)
    results = {}
    for href, title in parser.found:
        url = urllib.parse.urljoin(source["url"], unescape(href))
        if not allow_url(url, source):
            continue
        # Cafe24 themes sometimes keep product names outside the <a> tag,
        # but still put the full product name into the link's slug.
        slug = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        slug_ok = (source["type"] == "cafe24"
                   and re.search(r"ps5[-_\s]*pro|playstation[-_\s]*5[-_\s]*pro|플레이스테이션[-_\s]*5[-_\s]*프로", slug, re.I)
                   and not EXCLUDE.search(slug)
                   and not re.search(r"듀얼센스|디스크드라이브|번들|세트|중고|리퍼", slug, re.I))
        if acceptable_title(title) or slug_ok:
            label = re.sub(r"\s+", " ", unescape(title)).strip()[:140]
            if not acceptable_title(label):
                label = slug.rsplit("/", 2)[-2][:140]
            results[url] = label

    # SSG also renders product entries as embedded itemNm/itemId JSON.
    if source["type"] == "ssg":
        for match in re.finditer(r'"itemNm"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"(?:(?!\{).){0,1400}?"itemId"\s*:\s*"(\d{10,16})"', html, re.I | re.S):
            try:
                name = json.loads('"' + match.group(1) + '"')
            except ValueError:
                continue
            if acceptable_title(name):
                url = f"https://www.ssg.com/item/itemView.ssg?itemId={match.group(2)}"
                results[url] = name[:140]
    return results

def gh(path, payload=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    return json.loads(request(f"https://api.github.com/repos/{repo}/{path}",
                              data, headers, method="PUT" if payload is not None else "GET"))

def load():
    try:
        obj = gh(f"contents/{STATE_PATH}")
        return json.loads(base64.b64decode(obj["content"]).decode()), obj["sha"]
    except HTTPError as exc:
        if exc.code == 404:
            return {}, None
        raise

def save(state, sha):
    data = {"message": "chore: record new product URLs",
            "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
    if sha:
        data["sha"] = sha
    gh(f"contents/{STATE_PATH}", data)

def main():
    if not monitor_window.is_active_at():
        print("Watch expired; skip product listing requests and alerts")
        return
    state, sha = load()
    changed = False
    discovered = 0
    alerts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(request, src["url"]): src for src in STORE_LISTS}
        for future in concurrent.futures.as_completed(tasks):
            src = tasks[future]
            try:
                pages = []
                try:
                    pages.append((src["url"], future.result()))
                except Exception as exc:
                    print(f"CATALOG PRIMARY UNAVAILABLE {src['name']}: {type(exc).__name__}: {exc}")
                for fallback in src.get("alternate_urls", []):
                    try:
                        pages.append((fallback, request(fallback)))
                    except Exception as exc:
                        print(f"CATALOG PUBLIC ALTERNATIVE UNAVAILABLE {src['name']}: {type(exc).__name__}: {exc}")
                if not pages:
                    raise RuntimeError("all public catalog and search pages unavailable")
                matches = {}
                for page_url, page in pages:
                    matches.update(discover(src, page))
                html = pages[0][1]
                if src["id"] == "getthese":
                    # The store may place newly published consoles in a
                    # separate PlayStation subcategory rather than the main
                    # product category (cate_no=23).
                    nav = Links()
                    nav.feed(html)
                    subcategories = []
                    for href, title in nav.found:
                        url = urllib.parse.urljoin(src["url"], unescape(href))
                        host = urllib.parse.urlparse(url).hostname or ""
                        if (("플레이스테이션" in title or "PlayStation" in title)
                            and host in ("get-these.com", "www.get-these.com")
                            and ("/category/" in url or "cate_no=" in url)):
                            subcategories.append(url)
                    for url in sorted(set(subcategories))[:2]:
                        try:
                            matches.update(discover(src, request(url)))
                            print(f"GetThese PlayStation subcategory checked: {url}")
                        except Exception as exc:
                            print(f"GetThese subcategory unavailable: {type(exc).__name__}: {exc}")
            except Exception as exc:
                print(f"CATALOG UNAVAILABLE {src['name']}: {type(exc).__name__}: {exc}")
                continue
            if not matches:
                print(f"NO VERIFIED PRODUCT LINKS {src['name']}: page accessible but no matching PS5 Pro listings; do not claim full listing coverage")
                continue
            print(f"{src['name']}: {len(matches)} matching links")
            # First successful scan establishes baseline. Existing product
            # pages are covered separately by the direct stock monitor.
            old = state.get(src["id"])
            if old is None:
                state[src["id"]] = sorted(matches)
                changed = True
                print(f"Baseline captured for {src['name']}; no retrospective alerts")
                continue
            fresh = sorted(set(matches) - set(old))
            for url in fresh:
                alerts.append((src["name"], matches[url], url))
            updated = sorted(set(old) | set(matches))[-400:]
            if updated != old:
                state[src["id"]] = updated
                changed = True
            discovered += len(fresh)

    # Send one compact digest if many new URLs appear in the same run.
    if alerts:
        groups = [alerts[i:i + MAX_ALERTS] for i in range(0, len(alerts), MAX_ALERTS)]
        for group in groups:
            entries = "\n\n".join(
                f"{name}\n{title}\n{url}" for name, title, url in group)
            telegram("[PS5 Pro 새 판매 페이지 발견 — 확인 필요]\n"
                     "새 상품 링크가 발견되었습니다. 재고·가격 미확정입니다.\n\n" + entries)
    if changed:
        save(state, sha)
    print(f"Catalog discovery complete; new URLs={discovered}, sources={len(STORE_LISTS)}")

if __name__ == "__main__":
    main()
