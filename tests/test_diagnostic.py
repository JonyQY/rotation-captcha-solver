import unittest

from spincap.diagnostic import (choose_page, classify, is_target, numeric_verdict,
                                rotation_degrees)


class DiagnosticTests(unittest.TestCase):
    def test_login_completed_in_new_tab_is_discovered_without_closing_tabs(self):
        class Page:
            def __init__(self, url, logged_in):
                self.url, self.logged_in = url, logged_in

            def is_closed(self):
                return False

            def locator(self, selector):
                return self

            def is_visible(self):
                return self.logged_in

        original = Page('https://ziyuan.baidu.com/dashboard/index', True)
        latest = Page('https://ziyuan.baidu.com/linksubmit/url', True)
        class Context:
            pages = [original, latest]
        self.assertIs(choose_page(Context(), original), latest)
        Context.pages = [original]
        self.assertIs(choose_page(Context(), original), original)

    def test_response_report_never_includes_credentials(self):
        self.assertEqual(numeric_verdict({
            'code': 0, 'tk': 'private', 'data': {'op': 3, 'opp': 1,
            'ds': 'private', 'tk': 'private', 'as': 'private'},
        }), {'code': 0, 'op': 3, 'opp': 1})
        self.assertEqual(numeric_verdict({'status': True, 'code': 'private'}), {})
        self.assertEqual(numeric_verdict(['private']), {})

    def test_only_the_expected_site_and_path_can_run(self):
        self.assertTrue(is_target('https://ziyuan.baidu.com/linksubmit/url'))
        for url in ('http://ziyuan.baidu.com/linksubmit/url',
                    'https://ziyuan.baidu.com.attacker.test/linksubmit/url',
                    'https://ziyuan.baidu.com/login/index'):
            self.assertFalse(is_target(url))

    def test_business_rejection_is_separate_from_widget_success(self):
        samples = [{'visible': ['验证通过']}]
        self.assertEqual(classify(samples, []), 'widget_success_business_unconfirmed')
        self.assertEqual(classify(samples, [{'path':'/linksubmit/urlsubmit', 'status_code':101}]),
                         'business_verification_rejected')
        self.assertEqual(classify(samples, [{'path':'/linksubmit/urlsubmit', 'status_code':0}]),
                         'business_success')

    def test_replacement_and_silence_never_count_as_success(self):
        self.assertEqual(classify([{'image_changed':True}], []), 'challenge_replaced_reason_unknown')
        self.assertEqual(classify([], [{'op':3}]), 'captcha_rejected')
        self.assertEqual(classify([], []), 'no_conclusive_verdict')

    def test_actual_css_rotation_is_reported_in_degrees(self):
        self.assertEqual(rotation_degrees('matrix(0, -1, 1, 0, 87, 0)'), 270)
        self.assertEqual(rotation_degrees('none'), 0)
        self.assertIsNone(rotation_degrees(None))


if __name__ == '__main__':
    unittest.main()
