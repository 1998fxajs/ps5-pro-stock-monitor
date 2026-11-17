"""Regression tests for new-product catalog link detection and expiry."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import catalog_watch as c
import monitor_window

class CatalogTests(unittest.TestCase):
    def test_gamewoori_new_product_url(self):
        html = '<a href="/product/ps5-pro-new/19999">PlayStation 5 Pro 콘솔 2TB</a>'
        out = c.discover(c.STORE_LISTS[0], html)
        self.assertEqual(len(out), 1)
        self.assertTrue(next(iter(out)).endswith("/19999"))

    def test_getthese_new_product_page(self):
        html = '<a href="/product/ps5-pro-new/899/category/23/display/1/"><img alt="PS5 Pro 콘솔 2TB"></a>'
        out = c.discover(c.STORE_LISTS[1], html)
        self.assertEqual(len(out), 1)

    def test_ssg_new_listing_data(self):
        html = '<script>{"itemNm":"플레이스테이션 5 프로 2TB 콘솔","itemId":"1000619325394"}</script>'
        out = c.discover(c.STORE_LISTS[2], html)
        self.assertEqual(len(out), 1)

    def test_console_bundles_reach_body_review(self):
        for name in ('PS5 Pro 2TB + 듀얼센스 세트','PS5 Pro 본체 + 디스크 드라이브'):
            html='<a href="/product/bundle/19999">'+name+'</a>'
            self.assertEqual(len(c.discover(c.STORE_LISTS[0],html)),1)

    def test_accessory_only_is_not_a_console_bundle(self):
        html='<a href="/product/drive/19999">PS5 Pro 디스크 드라이브 단품</a>'
        self.assertEqual(c.discover(c.STORE_LISTS[0],html),{})

    def test_wrong_host_not_allowed(self):
        self.assertFalse(c.allow_url("https://evilgamewoori.com/product/ps5-pro/16602", c.STORE_LISTS[0]))

    def test_catalogue_sources_preserved_with_marketplaces_in_retail_watch(self):
        self.assertEqual(len(c.STORE_LISTS), 4)
        self.assertTrue(all("gmarket" not in x["id"] for x in c.STORE_LISTS))

    def test_deadline_korea(self):
        kst = ZoneInfo("Asia/Seoul")
        self.assertTrue(monitor_window.is_active_at(datetime(2026,11,19,23,59,tzinfo=kst)))
        self.assertFalse(monitor_window.is_active_at(datetime(2026,11,20,0,0,tzinfo=kst)))

if __name__ == "__main__":
    unittest.main()
