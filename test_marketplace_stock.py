"""Real public-page reductions plus explicitly synthetic stock transitions."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import marketplace_stock as m
import retail_watch as r

ROOT = Path(__file__).with_name('fixtures')
GM = next(s for s in r.STORES if s['type'] == 'gmarket')
NV = next(s for s in r.STORES if s['type'] == 'naver')


def fixture(name):
    return (ROOT / (name + '.html')).read_text(encoding='utf-8')


def gm_page(goods, event):
    return '<script>var goods = '+json.dumps(goods)+';var eventObj = '+json.dumps(event)+';</script>'


def nv_page(state):
    return '<script>window.__PRELOADED_STATE__='+json.dumps(state)+';</script>'


class MarketplaceTests(unittest.TestCase):
    def setUp(self):
        html = fixture('gmarket_candidate_1')
        self.goods = m.assignment(html, 'goods')
        self.event = m.assignment(html, 'eventObj')
        self.naver = m.assignment(fixture('naver_catalogue'), '__PRELOADED_STATE__')

    def test_real_gmarket_raffle_is_sold_out(self):
        result = r.parse_product(GM, fixture('gmarket_candidate_1'))
        self.assertEqual(result['status'], 'out_of_stock')
        self.assertEqual(result['sale_mode'], 'raffle')

    def test_real_naver_catalogue_is_not_a_direct_product_read(self):
        html = fixture('naver_catalogue')
        self.assertEqual(r.parse_product(NV, html)['status'], 'unknown')
        result = m.naver(NV, html, catalogue=True)
        self.assertEqual(result['status'], 'out_of_stock')
        self.assertEqual(result['stock_quantity'], 0)
        self.assertEqual(result['evidence_type'], 'official_catalogue')

    def test_real_other_console_cannot_become_pro_stock(self):
        self.assertEqual(r.parse_product(GM, fixture('gmarket_structure'))['status'], 'unknown')

    def test_real_naver_primary_detail_summary_is_direct_inventory(self):
        html = fixture('naver_direct')
        with patch.object(r, 'fetch', return_value=html) as fetch:
            result = r.check_public(NV)
        self.assertEqual(result['status'], 'out_of_stock')
        self.assertEqual(result['evidence_type'], 'direct_product')
        self.assertEqual(result['stock_quantity'], 0)
        fetch.assert_called_once_with(NV['url'])

    def test_detail_summary_does_not_override_a_different_primary_item(self):
        state = m.assignment(fixture('naver_direct'), '__PRELOADED_STATE__')
        state['product']['id'] = 999
        self.assertEqual(m.naver(NV, nv_page(state))['status'], 'unknown')

    def test_gmarket_seller_change_blocks_stock_signal(self):
        self.goods['seller']['SellerId'] = 'different_seller'
        self.assertEqual(m.gmarket(GM, gm_page(self.goods, self.event))['status'], 'unknown')

    def test_raffle_activation_is_never_console_stock(self):
        self.goods['IsOutOfStock'] = False
        result = m.gmarket(GM, gm_page(self.goods, self.event))
        self.assertEqual(result['status'], 'raffle_signal')
        self.assertNotIn('price', result)

    def test_synthetic_gmarket_bundle_signal_requires_price_identity(self):
        self.goods.update(GoodsName='PS5 Pro 콘솔 2TB + 게임 세트', IsOutOfStock=False)
        self.event['price'] = 1_399_000
        result = m.gmarket(GM, gm_page(self.goods, self.event))
        self.assertEqual(result['status'], 'stock_signal')
        self.assertTrue(result['above_standalone_price'])
        self.event['itemId'] = 'another_product'
        self.assertEqual(m.gmarket(GM, gm_page(self.goods, self.event))['status'], 'unknown')

    def test_placeholder_price_and_missing_boolean_are_not_stock(self):
        self.goods.update(GoodsName='PS5 Pro 콘솔 2TB', IsOutOfStock=False)
        self.assertEqual(m.gmarket(GM, gm_page(self.goods, self.event))['status'], 'unknown')
        self.goods.pop('IsOutOfStock')
        self.event['price'] = 1_298_000
        self.assertEqual(m.gmarket(GM, gm_page(self.goods, self.event))['status'], 'unknown')

    def test_accessory_name_does_not_pass(self):
        self.goods['GoodsName'] = 'PS5 Pro 전용 디스크 드라이브'
        self.assertEqual(m.gmarket(GM, gm_page(self.goods, self.event))['status'], 'unknown')

    def test_naver_recommendations_are_not_inventory(self):
        self.naver['relationProducts'] = self.naver.pop('categoryProducts')
        self.assertEqual(m.naver(NV, nv_page(self.naver), catalogue=True)['status'], 'unknown')

    def test_naver_wrong_seller_and_other_item_are_not_stock(self):
        product = self.naver['categoryProducts']['simpleProducts'][0]
        product['channel']['channelNo'] = 123
        self.assertEqual(m.naver(NV, nv_page(self.naver), catalogue=True)['status'], 'unknown')
        product['channel']['channelNo'] = int(NV['channel_id'])
        product['id'] = 123
        self.assertEqual(m.naver(NV, nv_page(self.naver), catalogue=True)['status'], 'unknown')

    def test_synthetic_naver_sale_requires_positive_quantity(self):
        product = self.naver['categoryProducts']['simpleProducts'][0]
        product['productStatusType'] = 'SALE'
        self.assertEqual(m.naver(NV, nv_page(self.naver), catalogue=True)['status'], 'out_of_stock')
        product['stockQuantity'] = 3
        self.assertEqual(m.naver(NV, nv_page(self.naver), catalogue=True)['status'], 'stock_signal')
        self.naver['product'] = product
        self.assertEqual(m.naver(NV, nv_page(self.naver))['evidence_type'], 'direct_product')
        product['saleType'] = 'USED'
        self.assertEqual(m.naver(NV, nv_page(self.naver))['status'], 'unknown')

    def test_undefined_replacement_does_not_modify_strings_or_eval(self):
        html = '<script>window.__PRELOADED_STATE__={"x":undefined,"name":"undefined"};throw Error("must not execute");</script>'
        self.assertEqual(m.assignment(html, '__PRELOADED_STATE__'), {'x': None, 'name': 'undefined'})

    def test_direct_block_remains_visible_with_catalogue_evidence(self):
        denied = HTTPError(NV['url'], 429, 'limited', None, None)
        with patch.object(r, 'fetch', side_effect=[denied, fixture('naver_catalogue')]) as fetch:
            result = r.check_public(NV)
        self.assertEqual(result['direct_status'], 'access_denied')
        self.assertEqual(result['direct_http_status'], 429)
        self.assertEqual(result['status'], 'out_of_stock')
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [NV['url'], NV['catalogue_url']])

    def test_all_blocked_is_not_sold_out(self):
        with patch.object(r, 'fetch', side_effect=HTTPError(NV['url'], 429, 'limited', None, None)):
            self.assertEqual(r.check_public(NV)['status'], 'access_denied')
        for code, status in [(403, 'access_denied'), (429, 'access_denied'), (500, 'unavailable')]:
            with patch.object(r, 'fetch', side_effect=HTTPError(GM['url'], code, 'failed', None, None)):
                self.assertEqual(r.check_public(GM)['status'], status)

    def run_transition(self, previous, fail=False):
        result = {'status': 'stock_signal', 'reason': 'synthetic test',
                  'price': 1_399_000, 'product_name': 'PS5 Pro 본체 포함 세트',
                  'above_standalone_price': True}
        with patch.object(r, 'STORES', [GM]), patch.object(r.monitor_window, 'is_active_at', return_value=True), \
             patch.object(r, 'load_state', return_value=(copy.deepcopy(previous), 'sha')), \
             patch.object(r, 'check_public', return_value=result), \
             patch.object(r, 'telegram', side_effect=RuntimeError('delivery failed') if fail else None) as send, \
             patch.object(r, 'save_state') as save:
            if fail:
                with self.assertRaises(RuntimeError):
                    r.main()
            else:
                r.main()
            return send, save

    def test_transition_delivers_once_and_records_only_after_success(self):
        send, save = self.run_transition({GM['id']: {'status': 'out_of_stock'}})
        self.assertEqual(send.call_count, 1)
        self.assertIn('PS5 Pro 본체 포함 세트', send.call_args.args[0])
        state = save.call_args.args[0]
        send, _ = self.run_transition(state)
        send.assert_not_called()
        _, save = self.run_transition({}, fail=True)
        save.assert_not_called()

    def test_dry_run_does_not_save_retail_state(self):
        with patch.dict('os.environ', {'MONITOR_DRY_RUN': '1'}), patch.object(r, 'gh') as gh:
            r.save_state({'status': 'test'}, 'sha')
            gh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
