"""Parse public marketplace page data without executing page JavaScript.

Only the registered item and verified seller are stock evidence. Catalogue
evidence is explicitly weaker than a successful direct product-page read.
"""
import json
import re
from html.parser import HTMLParser
import sale_link_review


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = True
            self.scripts.append('')

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.scripts[-1] += data


def assignment(html, variable):
    parser = Scripts()
    parser.feed(html)
    prefix = r'(?:var\s+|window\.)' + re.escape(variable) + r'\s*=\s*'
    for script in parser.scripts:
        match = re.search(prefix, script)
        if not match:
            continue
        raw = script[match.end():]
        # Naver serializes undefined as a JS literal. Replace only unquoted
        # tokens; never eval page code or change a product's string contents.
        raw = re.sub(r'"(?:\\.|[^"\\])*"|\bundefined\b',
                     lambda m: 'null' if m[0] == 'undefined' else m[0], raw)
        try:
            value, _ = json.JSONDecoder().raw_decode(raw)
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            pass
    return {}


def unknown(reason):
    return {'status': 'unknown', 'reason': reason}


def target_name(name):
    return (isinstance(name, str) and sale_link_review.console_subject(name, False)
            and not re.search(r'중고|리퍼|해외직구|대여|렌탈', name, re.I))


def valid_price(value):
    # A raffle/application placeholder price (e.g. 100 KRW) is not a console.
    if isinstance(value, bool):
        return None
    try:
        value = float(str(value).replace(',', ''))
        return int(value) if 300_000 <= value < 100_000_000 else None
    except (TypeError, ValueError):
        return None


def gmarket(store, html):
    goods = assignment(html, 'goods')
    if str(goods.get('GoodsCode')) != store['product_id']:
        return unknown('Gmarket primary goods ID missing or mismatched')
    seller = goods.get('seller') or {}
    if (seller.get('SellerId') != store['seller_id']
            or goods.get('IsSellerOfficial') is not True):
        return unknown('Gmarket verified official seller identity missing or mismatched')
    name = goods.get('GoodsName', '')
    if not target_name(name):
        return unknown('Gmarket primary item is not a new PS5 Pro console-containing product')
    raffle = bool(re.search(r'추첨|응모|당첨', name))
    common = {'product_name': name, 'product_id': store['product_id'],
              'seller_id': store['seller_id'], 'evidence_type': 'direct_product',
              'sale_mode': 'raffle' if raffle else 'sale'}
    if goods.get('IsOutOfStock') is True:
        return dict(common, status='out_of_stock', reason='primary goods.IsOutOfStock=true')
    if goods.get('IsOutOfStock') is not False:
        return unknown('Gmarket explicit stock boolean missing')
    if raffle:
        return dict(common, status='raffle_signal',
                    reason='raffle item IsOutOfStock=false; console purchase stock not established')
    event = assignment(html, 'eventObj')
    price = valid_price(event.get('price'))
    if (str(event.get('itemId')) != store['product_id']
            or event.get('currency') != 'KRW' or price is None):
        return unknown('Gmarket sale signal lacks a matching console price and currency')
    return dict(common, status='stock_signal', price=price,
                above_standalone_price=price > 1_298_000,
                reason='primary official goods.IsOutOfStock=false; checkout unverified')


def naver(store, html, catalogue=False):
    state = assignment(html, '__PRELOADED_STATE__')
    channel = state.get('channel') or {}
    if str(channel.get('id')) != store['channel_id']:
        return unknown('Naver official channel identity missing or mismatched')
    if catalogue:
        # Recommendations, best sellers and related products are NOT evidence.
        products = (state.get('categoryProducts') or {}).get('simpleProducts') or []
        product = next((p for p in products if isinstance(p, dict)
                        and str(p.get('id')) == store['product_id']), {})
    else:
        product = state.get('product') or {}
    if str(product.get('id')) != store['product_id']:
        return unknown('Naver requested product absent from primary product data')
    if str((product.get('channel') or {}).get('channelNo')) != store['channel_id']:
        return unknown('Naver product seller channel missing or mismatched')
    name = product.get('name', '')
    if not target_name(name) or product.get('saleType') != 'NEW':
        return unknown('Naver primary item is not a new PS5 Pro console-containing product')
    evidence = 'official_catalogue' if catalogue else 'direct_product'
    common = {'product_name': name, 'product_id': store['product_id'],
              'channel_id': store['channel_id'], 'evidence_type': evidence}
    status = product.get('productStatusType') or product.get('statusType')
    quantity = product.get('stockQuantity')
    if status == 'OUTOFSTOCK' or (status == 'SALE' and quantity == 0):
        return dict(common, status='out_of_stock', stock_quantity=quantity,
                    reason=f'{evidence} exact product status={status}, stockQuantity={quantity}')
    price = valid_price(product.get('salePrice'))
    if (status == 'SALE' and isinstance(quantity, int) and not isinstance(quantity, bool)
            and quantity > 0 and price is not None
            and product.get('channelProductDisplayStatusType') == 'ON'):
        # Option stock can differ from aggregate stock. Always retain a
        # cautious signal and let the buyer inspect the actual composition.
        return dict(common, status='stock_signal', price=price,
                    stock_quantity=quantity, above_standalone_price=price > 1_298_000,
                    reason=f'{evidence} exact product SALE with positive stock; checkout unverified')
    return unknown(f'Naver product state={status}; no validated positive stock signal')
