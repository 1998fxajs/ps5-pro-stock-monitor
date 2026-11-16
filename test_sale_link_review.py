"""Offline tests for extracting actionable, relevant PS5 Pro purchase/raffle URLs."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import sale_link_review as s

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=KST)

class SaleLinkTests(unittest.TestCase):
    def test_official_raffle_direct_link_and_schedule(self):
        page = """
        <article><h1>PS5 Pro 콘솔 - 2TB 1,298,000원 응모</h1>
        <p>응모 종료일시: 2026.11.22 23:59</p>
        <a href="https://playshop.co.kr/board/online_entry/list.html?board_no=16">응모하러 가기</a></article>
        """
        lead = s.review("PS5 Pro 단품 추첨 응모", "https://community.example.com/posted/27",
                        page, now=NOW)
        self.assertIsNotNone(lead)
        self.assertTrue(lead["direct_link"])
        self.assertEqual(lead["link"], "https://playshop.co.kr/board/online_entry/list.html?board_no=16")
        self.assertEqual(lead["deadline"], "2026-11-22 23:59 KST")
        self.assertIn(lead["link"], s.format_alert(lead, "커뮤니티", NOW))

    def test_reject_closed_headline(self):
        self.assertIsNone(s.review("PS5 Pro 응모 마감", "https://example.com/a", now=NOW))
        self.assertIsNone(s.review("PS5 Pro 품절 판매 종료", "https://example.com/a", now=NOW))

    def test_reject_expired_entry(self):
        html = "<p>응모 종료일시: 2026.11.15 23:59</p>"
        self.assertIsNone(s.review("PS5 Pro 추첨 접수", "https://example.com/a",html,now=NOW))

    def test_reject_over_budget_in_title(self):
        self.assertIsNone(s.review("PS5 Pro 콘솔 판매 1,480,000원", "https://example.com/a",now=NOW))

    def test_news_only_remains_unverified(self):
        lead = s.review("PS5 Pro 2TB 정가 재입고", "https://news.google.com/rss/articles/XYZ", now=NOW)
        self.assertFalse(lead["direct_link"])
        self.assertIn("직접 링크 미확인",s.format_alert(lead,"뉴스",NOW))

    def test_embedded_description_link(self):
        desc = '<a href="https://get-these.com/product/ps5-pro-console-2tb/426/">구매하러 가기</a>'
        lead = s.review("PS5 Pro 특가 재입고", "https://example.com/alert",description=desc,now=NOW)
        self.assertEqual(lead["link"],"https://get-these.com/product/ps5-pro-console-2tb/426/")

    def test_no_internal_network_requests(self):
        bad = [
            "http://127.0.0.1/secrets",
            "http://10.0.0.3/internal",
            "http://localhost/credentials",
            "file:///etc/passwd",
            "https://user:password@example.com/private",
        ]
        self.assertTrue(all(not s.safe_public_url(u) for u in bad))

    def test_reject_bundle_and_resale_headline(self):
        for title in ("PS5 Pro 울버린 특전 세트 판매", "PS5 Pro 중고 특가"):
            self.assertIsNone(s.review(title,"https://example.com/a",now=NOW))

    def test_news_link_with_official_specific_product_dominates(self):
        html = """
        <a href="https://www.youtube.com/watch?v=abc">영상 바로가기</a>
        <a href="https://playshop.co.kr/product/ps5-pro-new-2tb/399/">PS5 Pro 콘솔 2TB 상품 구매</a>
        """
        lead = s.review("PS5 Pro 신규 판매 페이지 오픈","https://example.com/post",html,now=NOW)
        self.assertEqual(lead["link"], "https://playshop.co.kr/product/ps5-pro-new-2tb/399/")

if __name__ == "__main__":
    unittest.main()
