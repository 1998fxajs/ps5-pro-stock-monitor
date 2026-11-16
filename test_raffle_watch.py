"""Offline tests: official PS5 Pro standalone raffles, bundles and expired rounds."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import raffle_watch as r

def block(label,price,start,end):
    return (
        "<div>뱃지 문구 | PS5 "
        "상품 URL | /product/detail.html?product_no=334 "
        f"정상가 | {price:,}원 판매가 | {price:,}원 "
        f"응모 시작일시 | {start} 응모 종료일시 | {end} "
        f"<h2>{label}</h2></div>")

class RaffleTests(unittest.TestCase):
    def test_standalone_only(self):
        html = (
            block("PS5 Pro 콘솔 + PS5 울버린 특전",1362800,
                  "2026.11.18 00:00","2026.11.22 23:59") +
            block("PS5 Pro 콘솔 + 듀얼센스 옵션 선택",1385500,
                  "2026.11.18 00:00","2026.11.22 23:59") +
            block("PS5 Pro 콘솔 - 2TB",1298000,
                  "2026.11.18 00:00","2026.11.22 23:59")
        )
        found=r.parse_rounds(html)
        self.assertEqual(len(found),1)
        obj=list(found.values())[0]
        self.assertEqual(obj["price"],1298000)
        self.assertEqual(obj["begin"],datetime(2026,11,18,0,0,tzinfo=ZoneInfo("Asia/Seoul")))
        self.assertEqual(obj["end"],datetime(2026,11,22,23,59,tzinfo=ZoneInfo("Asia/Seoul")))

    def test_no_mixed_bundle_price(self):
        html=block("PS5 Pro 콘솔 + 듀얼센스 옵션 선택",1385500,"2026.11.18 00:00","2026.11.22 23:59")
        self.assertEqual(r.parse_rounds(html),{})

    def test_invalid_dates_rejected(self):
        html=block("PS5 Pro 콘솔 - 2TB",1298000,"2026.11.23 00:00","2026.11.22 23:59")
        self.assertEqual(r.parse_rounds(html),{})

    def test_non_ps5_no_match(self):
        html=block("PS5 슬림 콘솔 - 1TB",1298000,"2026.11.18 00:00","2026.11.22 23:59")
        self.assertEqual(r.parse_rounds(html),{})

if __name__ == "__main__":
    unittest.main()
