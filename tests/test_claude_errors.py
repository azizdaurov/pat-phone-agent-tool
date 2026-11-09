import unittest

import claude_errors
from claude_errors import BUSY, LIMIT, LOGIN, OFFLINE, STARTING, plain_reason


class PlainReasonTest(unittest.TestCase):
    def test_claude_code_errors_become_steps_a_new_user_can_take(self):
        cases = {
            "Invalid API key · Please run /login": LOGIN,
            "OAuth token has expired. Please obtain a new token or refresh your existing token.": LOGIN,
            "Claude AI usage limit reached|1762700000": LIMIT,
            "API Error: Connection error.": OFFLINE,
            'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}': BUSY,
        }
        for raw, plain in cases.items():
            self.assertEqual(plain_reason(STARTING + raw), plain, raw)

    def test_a_reset_time_is_kept(self):
        self.assertEqual(plain_reason(STARTING + "You've hit your limit · resets 5pm (Asia/Tashkent)"),
                         "Your Claude plan's limit is used up. It resets 5pm (Asia/Tashkent).")

    def test_only_claudes_errors_are_changed(self):
        bluetooth = "iphonecall did not start: authentication failed on the network adapter"
        self.assertEqual(plain_reason(bluetooth), bluetooth)
        unknown = STARTING + "something new"
        self.assertEqual(plain_reason(unknown), unknown)
        self.assertEqual(plain_reason(None), "")

    def test_every_message_fits_on_the_note(self):
        from note import NOTICE_CHARS
        for message in (LOGIN, LIMIT, OFFLINE, BUSY):
            self.assertLessEqual(len(message), NOTICE_CHARS)
        self.assertTrue(claude_errors.PATTERNS)


if __name__ == "__main__":
    unittest.main()
