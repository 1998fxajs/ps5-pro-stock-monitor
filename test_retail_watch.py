"""Offline regression tests; do not depend on retailer/network access."""
import unittest
import retail_watch as m

STORES = {s['id']:s for s in m.STORES}
GAME = STORES['gamewoori']
SSG = STORES['ssg_emart']
COMPUZONE = STORES['compuzone']
GETTHESE = STORES['getthese']

def page(title, mark="", offers=""):
    return f"<html><head><title>{title}</title>{offers}</head><body><h1>{title} {mark}</h1></body></html>"

class RetailParsers(unittest.TestCase):
    def test_gamewoori_sold_out(self):
        html = page("PlayStation 5 프로 본체 2TB CFI-7122B", '<img alt="품절" src="/soldout.gif">')
        self.assertEqual(m.parse_product(GAME, html)["status"], "out_of_stock")

    def test_gamewoori_no_false_stock_from_buy_word(self):
        html = page("PlayStation 5 프로 본체 2TB CFI-7122B", "<button>구매하기</button>")
        self.assertEqual(m.parse_product(GAME, html)["status"], "unknown")

    def test_ssg_sold_out(self):
        html = page("플레이스테이션 5 프로", "sellStatCd=80")
        self.assertEqual(m.parse_product(SSG, html)["status"], "out_of_stock")

    def test_compuzone_not_buyable_from_generic_button(self):
        html = page("PlayStation5 Pro 콘솔", "구매하기 입고예정 미정")
        self.assertNotEqual(m.parse_product(COMPUZONE, html)["status"], "in_stock")

    def test_structured_instocks_require_price_and_currency(self):
        data = '{"@context":"https://schema.org","@type":"Product","name":"PlayStation 5 프로 본체 2TB CFI-7122B","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"1298000","priceCurrency":"KRW"}}'
        html = page("PlayStation 5 프로 본체 2TB CFI-7122B", offers=f'<script type="application/ld+json">{data}</script>')
        self.assertEqual(m.parse_product(GAME, html)["status"], "in_stock")

    def test_console_bundle_stock_is_not_discarded(self):
        data = '{"@type":"Product","name":"PlayStation 5 프로 본체 2TB CFI-7122B + 디스크 드라이브 세트","offers":{"availability":"https://schema.org/InStock","price":1298000,"priceCurrency":"KRW"}}'
        html = page("PlayStation 5 프로 본체 2TB CFI-7122B", offers=f'<script type="application/ld+json">{data}</script>')
        self.assertEqual(m.parse_product(GAME, html)["status"], "in_stock")

    def test_over_standalone_price_is_labelled_signal(self):
        data = '{"@type":"Product","name":"PlayStation 5 프로 본체 2TB CFI-7122B","offers":{"availability":"https://schema.org/InStock","price":1398000,"priceCurrency":"KRW"}}'
        html = page("PlayStation 5 프로 본체 2TB CFI-7122B", offers=f'<script type="application/ld+json">{data}</script>')
        result=m.parse_product(GAME, html)
        self.assertEqual(result['status'],'stock_signal')
        self.assertTrue(result['above_standalone_price'])

    def test_getthese_schema_instocks_are_not_confirmed_buyable(self):
        data = '{"@type":"Product","name":"PS5 Pro 콘솔 - 2TB 순차출고","offers":{"availability":"https://schema.org/InStock","price":1298000,"priceCurrency":"KRW"}}'
        html = page("PS5 Pro 콘솔 - 2TB 순차출고", offers=f'<script type="application/ld+json">{data}</script>')
        self.assertEqual(m.parse_product(GETTHESE, html)["status"], "stock_signal")

    def test_getthese_soldout_in_heading(self):
        html = page("PS5 Pro 콘솔 - 2TB 순차출고", '<img alt="품절" src="soldout.png">')
        self.assertEqual(m.parse_product(GETTHESE, html)["status"], "out_of_stock")

    def test_getthese_buy_button_without_stock_proof(self):
        html = page("PS5 Pro 콘솔 - 2TB 순차출고", "<button>구매하기</button>")
        self.assertEqual(m.parse_product(GETTHESE, html)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
