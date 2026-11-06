"""Default language checks that never start phone or audio services."""
import inspect
import json
import types
import unittest
from unittest import mock

import pat
import phone_mcp
from call_brief import CallBrief


class DefaultLanguage(unittest.TestCase):
    def test_briefs_default_to_english_and_keep_explicit_russian(self):
        values = {"goal": "Check hours", "name": "Alex", "confidence": "guess"}
        english = CallBrief.from_dict(values)
        self.assertEqual(english.language, "en")
        self.assertEqual(english.check_question(), "Could you tell me, please, is this Alex?")
        russian = CallBrief.from_dict({**values, "language": "ru"})
        self.assertEqual(russian.language, "ru")
        self.assertIn("Скажите", russian.check_question())

    def test_mcp_default_is_english(self):
        self.assertEqual(inspect.signature(phone_mcp.place_call).parameters["language"].default, "en")

    def test_brief_file_uses_cli_language_unless_the_file_sets_one(self):
        for cli, stored, expected in (("en", None, "en"), ("ru", None, "ru"), ("en", "ru", "ru")):
            data = {"goal": "Check opening hours"}
            if stored:
                data["language"] = stored
            with self.subTest(cli=cli, stored=stored), mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(data))):
                brief = pat.load_brief(types.SimpleNamespace(brief_file="fake.json", lang=cli, action="dial"))
            self.assertEqual(brief.language, expected)

    def test_cli_default_is_english_and_explicit_russian_is_kept(self):
        class StopBeforePhone(Exception):
            pass
        for arguments, expected in ((["answer"], "en"), (["answer", "--lang", "ru"], "ru")):
            captured = []
            def stop(parser, *args, **kwargs):
                captured.append(parser.parse_known_args(arguments)[0])
                raise StopBeforePhone()
            with self.subTest(arguments=arguments), mock.patch.object(pat.argparse.ArgumentParser, "parse_args", autospec=True, side_effect=stop):
                with self.assertRaises(StopBeforePhone):
                    pat.main()
            self.assertEqual(captured[0].lang, expected)


if __name__ == "__main__":
    unittest.main()
