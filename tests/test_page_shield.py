"""حماية مصدر الصفحات: صفحات HTML الكاملة تُرسل مشفّرة، وما سواها (JSON والملفات وأجزاء HTML) يبقى كما هو."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, jsonify  # noqa: E402

from app import page_shield  # noqa: E402


def _client(enabled=True):
    app = Flask(__name__)
    app.config['PAGE_SHIELD'] = enabled
    page_shield.install(app)
    app.add_url_rule('/page', 'page', lambda: '<!doctype html><html><head><title>سري</title></head><body><form id="f"></form></body></html>')
    app.add_url_rule('/fragment', 'fragment', lambda: '<div>جزء</div>')
    app.add_url_rule('/data', 'data', lambda: jsonify(ok=True))
    return app.test_client()


class PageShieldTest(unittest.TestCase):
    def test_full_pages_are_encoded(self):
        r = _client().get('/page')
        body = r.get_data(as_text=True)
        self.assertNotIn('<title>', body)
        self.assertNotIn('id="f"', body)
        self.assertIn('atob', body)
        self.assertEqual(r.headers['Cache-Control'], 'no-store')

    def test_fragments_and_json_are_untouched(self):
        c = _client()
        self.assertEqual(c.get('/fragment').get_data(as_text=True), '<div>جزء</div>')
        self.assertEqual(c.get('/data').get_json(), {'ok': True})

    def test_can_be_disabled(self):
        old = os.environ.get('PAGE_SHIELD')
        os.environ['PAGE_SHIELD'] = '0'
        try:
            self.assertIn('<title>', _client().get('/page').get_data(as_text=True))
        finally:
            os.environ.pop('PAGE_SHIELD', None)
            if old is not None:
                os.environ['PAGE_SHIELD'] = old


if __name__ == '__main__':
    unittest.main()
