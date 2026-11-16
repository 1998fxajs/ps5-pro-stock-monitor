"""Unit tests for PS5 Pro announcement variants and deal filters."""
import unittest
import promo_watch as p


class PromoTitleTests(unittest.TestCase):
    def test_product_aliases(self):
        titles = [
            "PS5 Pro 2TB 재입고", "PS5프로 정가 판매",
            "PS5 프로 2TB 선착순", "플레이스테이션5 프로 판매 시작",
            "플레이스테이션 5 프로 추첨 응모",
            "플레이스테이션5프로 재고", "플스5 프로 핫딜",
            "플스 5 프로 입고", "플스5프로 특가",
            "플스 프로 물량", "PlayStation 5 Pro 예약판매",
            "CFI-7122B 판매 오픈",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertIsNotNone(p.INCLUDE.search(title), title)
                self.assertIsNotNone(p.SIGNAL.search(title), title)
                self.assertIsNone(p.EXCLUDE.search(title), title)

    def test_accessories_and_used_listings_excluded(self):
        titles = [
            "PS5 Pro 보호필름 특가",
            "PS5 Pro 중고 판매",
            "PS5 Pro 디스크 드라이브 단품 입고",
            "PS5 Pro 울버린 번들 판매",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertIsNotNone(p.EXCLUDE.search(title), title)

    def test_playshop_search_only_coverage(self):
        queries = " ".join(query for label, query in p.FEEDS if "플레이샵" in label)
        self.assertIn("플레이샵", queries)
        self.assertIn("오진상사", queries)
        self.assertIn("site:playshop.co.kr", queries)
        self.assertIn("site:ojinplaystation.cafe24.com", queries)
        self.assertIn("site:ppomppu.co.kr", queries)
        self.assertGreaterEqual(len([1 for label, _ in p.FEEDS if "플레이샵" in label]), 3)

    def test_search_coverage(self):
        queries = " ".join(query for _, query in p.FEEDS)
        self.assertGreaterEqual(len(p.FEEDS), 10)
        for keyword in ("PS5 Pro", "PS5프로", "플레이스테이션 5 프로",
                        "플스5 프로", "겟디즈", "지마켓", "SSG", "이마트",
                        "4910", "CFI-7122B"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, queries)


if __name__ == "__main__":
    unittest.main()
