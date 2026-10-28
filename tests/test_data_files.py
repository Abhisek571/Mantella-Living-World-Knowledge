import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import build_lore as B  # noqa: E402

RULE = ("You only know what your background, memories and knowledge lines say, plus what "
        "anyone in Skyrim would know. You do not know quest secrets, puzzles, hidden mechanisms "
        "or places you have never been. When asked about such things, deflect in your own "
        "words.")


def read(*parts):
    with open(os.path.join(ROOT, "data", *parts), encoding="utf-8") as f:
        return f.read()


class DataFiles(unittest.TestCase):
    def test_knowledge_rule_exact_one_line(self):
        with open(os.path.join(ROOT, "SKSE", "Plugins", "MantellaSoftware", "data", "prompt_rules", "30_knowledge.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.strip(), RULE)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_common_knowledge_size(self):
        self.assertLessEqual(B.tokens(read("common_knowledge.txt")), 350)  # cached, but sent with every NPC

    def test_common_knowledge_has_no_secrets(self):
        text = read("common_knowledge.txt")
        for sid, rx in B.SECRET_RE.items():
            self.assertIsNone(rx.search(text), sid)


if __name__ == "__main__":
    unittest.main()
