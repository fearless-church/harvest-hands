import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('OVERFLOW_CLIENT_ID', 'test')
os.environ.setdefault('OVERFLOW_API_KEY', 'test')
import update_giving as giving

STOCK_ID = '6ac9402b7845f45a9ae9d1e8'

def stock(status='CONTRIBUTION_RECEIVED', **changes):
    return dict({'id': STOCK_ID, 'type': 'STOCK', 'status': status, 'amount': 96897.72}, **changes)

def cash(id='cash', amount=100):
    return {'id': id, 'type': 'CASH', 'status': 'PAID_OUT', 'amount': amount}

class Response:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data

class ReceivedTests(unittest.TestCase):
    def total(self, pages):
        with patch.object(giving, 'api_get', side_effect=[Response(p) for p in pages]), contextlib.redirect_stdout(io.StringIO()):
            return giving.get_all_contributions('campaign')

    def test_verified_net_receipt_survives_status_transitions(self):
        for status in giving.INCLUDE_STATUSES | {'CONTRIBUTION_RECEIVED'}:
            with self.subTest(status=status):
                self.assertEqual(giving.contribution_cents(stock(status)), 9399079)

    def test_reported_amount_change_does_not_add_or_replace_verified_deposit(self):
        for amount in [96897.72, 93990.79, 100000]:
            self.assertEqual(giving.contribution_cents(stock(amount=amount)), 9399079)

    def test_reversed_gift_is_not_counted(self):
        for status in giving.REVERSED_STATUSES:
            self.assertEqual(giving.contribution_cents(stock(status)), 0)

    def test_unrecognized_status_or_changed_type_fails(self):
        for c in [stock('UNRECOGNIZED'), stock(type='CASH')]:
            with self.assertRaises(ValueError): giving.contribution_cents(c)

    def test_other_stock_gift_does_not_inherit_correction(self):
        self.assertEqual(giving.contribution_cents(stock(id='different')), 0)
        self.assertEqual(giving.contribution_cents(stock('PAID_OUT', id='different')), 9689772)

    def test_existing_cash_and_exact_cents(self):
        for status in giving.INCLUDE_STATUSES:
            self.assertEqual(giving.contribution_cents(dict(cash(amount=10.29), status=status)), 1029)

    def test_duplicate_counts_once_and_current_total(self):
        self.assertEqual(self.total([{'data': [cash(amount=608606.13), stock(), stock()]}]), 702596.92)

    def test_missing_stock_is_not_added_as_a_constant(self):
        self.assertEqual(self.total([{'data': [cash()]}]), 100)

    def test_conflicting_duplicate_aborts(self):
        with self.assertRaises(ValueError): self.total([{'data': [stock(), stock('PAID_OUT')]}])

    def test_pagination_continues_past_incorrect_total_count(self):
        page1 = [cash(str(i), amount=1) for i in range(100)]
        self.assertEqual(self.total([{'data': page1, 'totalCount': 1}, {'data': [stock(), page1[0]], 'totalCount': 1}]), 94090.79)

    def test_empty_and_invalid_response_aborts(self):
        for body in [{'data': []}, {}, {'data': None}, {'data': [dict(cash(), id='')]}]:
            with self.assertRaises(ValueError): self.total([body])

    def test_public_page_update_is_received_only(self):
        original = Path('index.html').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'index.html'
            target.write_text(original)
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                with contextlib.redirect_stdout(io.StringIO()): giving.update_html(702596.92, giving.CHURCH_CONTRIBUTION)
            finally:
                os.chdir(previous)
            result = target.read_text()
            self.assertIn('data-received="843873.84"', result)
            self.assertIn('data-raised="843874"', result)
            self.assertNotIn('data-pledged=', result)

    def test_no_campaign_summary_fallback(self):
        source = Path('update_giving.py').read_text()
        self.assertNotIn('get_summary_total', source)
        self.assertNotIn('totalContributionValue', source)

if __name__ == '__main__': unittest.main()
