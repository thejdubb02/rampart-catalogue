"""Checker tests for the catalogue index."""

import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import build_index

BUILTIN_KEYS = {
    "rampart-light",
    "rampart-dark",
    "clique-dark",
    "light",
    "dracula",
    "nord",
    "gruvbox",
    "tokyonight",
    "solarized",
    "trinity",
    "paper",
    "plumber",
    "triforce",
    "fellowship",
    "drizzt",
    "chompy",
    "bricks",
    "aincrad",
}
BUILTIN_LABELS = {
    "rampart light",
    "rampart dark",
    "clique dark",
    "clique light",
    "dracula",
    "nord",
    "gruvbox",
    "tokyo night",
    "solarized dark",
    "trinity",
    "paper (light)",
    "plumber",
    "triforce",
    "fellowship",
    "drizzt",
    "chompy",
    "bricks",
    "aincrad",
}
LIGHT = {"sandstone", "glacier", "sage", "lavender-mist"}
DARK = {"graphite", "deep-sea", "ember", "plum"}
HYBRID = {"harbour-fog", "espresso-cream", "charcoal-rose"}
PROMPTS = {"action-items", "reply-in-three-lines"}
TEMPLATES = {
    "out-of-office",
    "follow-up",
    "meeting-request",
    "thanks-received",
    "invoice-reminder",
    "decline-politely",
    "intro-two-people",
    "not-the-right-person",
}
ITEM_KEYS = ["kind", "id", "name", "description", "author", "path", "size", "sha256", "preview"]
FORBIDDEN = {"\u2014": "em dash", "\u2013": "en dash", "\u2026": "ellipsis"}


def _theme(**overrides):
    data = {
        "name": "Ink",
        "dark": True,
        "background": "#000000",
        "surface": "#111111",
        "surfaceVariant": "#1C1C1C",
        "selection": "#222222",
        "text": "#FFFFFF",
        "muted": "#C0C0C0",
        "line": "#333333",
        "accent": "#FFD000",
        "onAccent": "#000000",
        "description": "A fixture theme for the checker.",
    }
    data.update(overrides)
    return data


def _page():
    return {
        "background": "#FFFFFF",
        "surface": "#F7F7F7",
        "surfaceVariant": "#ECECEC",
        "selection": "#D9E6F5",
        "text": "#111111",
        "muted": "#5C5C5C",
        "line": "#E0E0E0",
        "accent": "#0B3F8A",
        "onAccent": "#FFFFFF",
    }


def _template(**overrides):
    data = {
        "name": "Hello",
        "subject": "Hello {{first name}}",
        "body": "Hello {{ name }}.\n\nThis is {{me}} writing about {{subject}} to {{email}}.",
        "description": "A fixture template.",
    }
    data.update(overrides)
    return data


def _dump(data, indent=2):
    return (json.dumps(data, indent=indent) + "\n").encode("utf-8")


class BuildIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "themes").mkdir()
        (self.root / "templates").mkdir()
        (self.root / "prompts").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _reset(self):
        for folder in ("themes", "templates", "prompts"):
            for child in (self.root / folder).iterdir():
                child.unlink()

    def _write(self, kind, item_id, data):
        folder = {"theme": "themes", "template": "templates", "prompt": "prompts"}[kind]
        path = self.root / folder / f"{item_id}.json"
        # Indent 4 so the bytes are not a re-serialisation with the index renderer.
        path.write_bytes(_dump(data, indent=4))
        return path

    def _errors(self):
        try:
            build_index.build_index(self.root)
        except build_index.CatalogueError as error:
            return error.errors
        self.fail("expected the catalogue to be rejected")

    def test_valid_theme_and_template(self):
        self._write("theme", "aaa-ink", _theme())
        self._write("template", "zzz-note", _template())
        index = build_index.build_index(self.root)

        self.assertEqual(index["version"], 1)
        self.assertEqual(list(index), ["version", "items"])
        self.assertEqual([item["kind"] for item in index["items"]], ["template", "theme"])
        self.assertEqual([item["id"] for item in index["items"]], ["zzz-note", "aaa-ink"])

        template, theme = index["items"]
        self.assertEqual(list(template), ITEM_KEYS)
        self.assertEqual(list(theme), ITEM_KEYS)
        self.assertEqual(template["author"], "Rampart")
        self.assertEqual(theme["author"], "Rampart")
        self.assertEqual(template["path"], "templates/zzz-note.json")
        self.assertEqual(theme["path"], "themes/aaa-ink.json")
        self.assertEqual(
            template["preview"],
            {"subject": "Hello {{first name}}", "firstLine": "Hello {{ name }}."},
        )
        self.assertEqual(
            list(theme["preview"]),
            ["dark", "background", "surface", "text", "accent"],
        )
        self.assertEqual(theme["preview"]["background"], "#000000")
        self.assertNotIn("page", theme["preview"])

        for item in index["items"]:
            raw = (self.root / item["path"]).read_bytes()
            self.assertEqual(item["size"], len(raw))
            self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())

        text = build_index.render_index(index)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))
        self.assertTrue(text.startswith('{\n  "version": 1,\n  "items": [\n'))
        head = text.split('"preview"', 1)[0]
        positions = [head.index(f'"{key}"') for key in ITEM_KEYS if key != "preview"]
        self.assertEqual(positions, sorted(positions))

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_index.main(self.root), 0)
            written = (self.root / "index.json").read_bytes()
            self.assertEqual(written, text.encode("utf-8"))
            self.assertEqual(build_index.main(self.root), 0)
        self.assertEqual((self.root / "index.json").read_bytes(), written)

    def test_prompt_rules(self):
        good = {"name": "Brief", "description": "Keep it short.", "text": "Be brief.\nThree lines at most."}
        self._write("prompt", "brief", good)
        item = build_index.build_index(self.root)["items"][0]
        self.assertEqual((item["kind"], item["path"]), ("prompt", "prompts/brief.json"))
        self.assertEqual(item["preview"], {"summary": "Be brief."})

        for bad, needle in (
            ({**good, "text": "x" * 2001}, "over the 2000 cap"),
            ({**good, "text": "see\u200bthis"}, "text contains a character"),
            ({**good, "name": "Go\u202eback"}, "name contains a character"),
            ({**good, "text": "  "}, "text must be a non-empty string"),
            ({**good, "extra": "x"}, "unknown field extra"),
        ):
            self._reset()
            self._write("prompt", "brief", bad)
            self.assertTrue(any(needle in error for error in self._errors()), (bad, needle))

    def test_failed_build_does_not_replace_index(self):
        self._write("theme", "ink", _theme(line="nope"))
        (self.root / "index.json").write_text("old\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), "old\n")

    def test_missing_colour_is_rejected(self):
        data = _theme()
        del data["line"]
        self._write("theme", "ink", data)
        self.assertEqual(self._errors(), ["themes/ink.json: missing line"])

    def test_bad_hex_is_rejected(self):
        self._write("theme", "ink", _theme(accent="red"))
        self.assertEqual(self._errors(), ["themes/ink.json: accent is not #RRGGBB ('red')"])

    def test_contrast_is_rejected(self):
        self._write("theme", "ink", _theme(surface="#FFFFFF"))
        self.assertEqual(
            self._errors(),
            ["themes/ink.json: text on surface contrast is 1.00, needs 4.5"],
        )

    def test_size_cap(self):
        ok = self._sized(8192)
        (self.root / "themes" / "sized-ok.json").write_bytes(ok)
        index = build_index.build_index(self.root)
        self.assertEqual(index["items"][0]["size"], 8192)
        self.assertEqual(index["items"][0]["sha256"], hashlib.sha256(ok).hexdigest())

        self._reset()
        over = self._sized(8193)
        (self.root / "themes" / "sized-over.json").write_bytes(over)
        self.assertEqual(
            self._errors(),
            ["themes/sized-over.json: file is 8193 bytes, over the 8192 byte cap"],
        )

    def test_unknown_placeholder_is_rejected(self):
        self._write("template", "hello-note", _template(body="Hello {{date}}."))
        self.assertEqual(
            self._errors(),
            ["templates/hello-note.json: unknown placeholder {{date}}"],
        )

    def test_ids_match_pattern_and_are_unique(self):
        cases = [
            ("aa", True),
            ("a" * 41, True),
            ("a", False),
            ("a" * 42, False),
            ("Bad", False),
            ("-ab", False),
            ("ab_c", False),
        ]
        for stem, ok in cases:
            with self.subTest(stem=stem, ok=ok):
                self._reset()
                self._write("theme", stem, _theme())
                if ok:
                    index = build_index.build_index(self.root)
                    self.assertEqual([item["id"] for item in index["items"]], [stem])
                else:
                    errors = self._errors()
                    self.assertTrue(any(stem in error and "does not match" in error for error in errors))
                    self.assertTrue(any(build_index.ID_RE.pattern in error for error in errors))

        self._reset()
        self._write("template", "same-item", _template())
        self._write("theme", "same-item", _theme())
        self.assertEqual(
            self._errors(),
            ["themes/same-item.json: id same-item is already used by templates/same-item.json"],
        )

    def test_page_rules(self):
        self._write("theme", "hybrid-ink", _theme(page=_page()))
        index = build_index.build_index(self.root)
        preview = index["items"][0]["preview"]
        self.assertEqual(list(preview["page"]), ["background", "text", "accent"])
        self.assertGreater(build_index.relative_luminance(preview["page"]["background"]), 0.5)

        self._reset()
        self._write("theme", "hybrid-ink", _theme(dark=False, page=_page()))
        self.assertEqual(
            self._errors(),
            ["themes/hybrid-ink.json: page is only allowed when dark is true"],
        )

        self._reset()
        dark_page = {key: _theme()[key] for key in build_index.THEME_COLOURS}
        self._write("theme", "hybrid-ink", _theme(page=dark_page))
        errors = self._errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("background luminance is ", errors[0])
        self.assertIn("needs to be over 0.5", errors[0])

        self._reset()
        weak = _page()
        weak["text"] = "#F0F0F0"
        weak["surface"] = "#000000"
        weak["muted"] = "#333333"
        self._write("theme", "ink", _theme(page=weak))
        errors = self._errors()
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("themes/ink.json page: text on background contrast is "))
        self.assertTrue(errors[0].endswith(", needs 4.5"))

    def _sized(self, size):
        data = _theme()
        data["description"] = "A."
        gap = size - len(_dump(data))
        self.assertGreaterEqual(gap, 0)
        data["description"] = "A" + ("a" * gap) + "."
        raw = _dump(data)
        self.assertEqual(len(raw), size, len(raw))
        return raw

    def test_shipped_catalogue(self):
        root = build_index.ROOT
        index = build_index.build_index(root)
        text = build_index.render_index(index)
        self.assertEqual((root / "index.json").read_text(encoding="utf-8"), text)

        kinds = {}
        for item in index["items"]:
            kinds.setdefault(item["kind"], set()).add(item["id"])
            self.assertEqual(list(item), ITEM_KEYS)
            self.assertEqual(item["author"], "Rampart")
            raw = (root / item["path"]).read_bytes()
            self.assertEqual(item["size"], len(raw))
            self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(_terminator_count(item["description"]), 1)
            self.assertNotIn(item["id"], BUILTIN_KEYS)
            self.assertNotIn(item["name"].lower(), BUILTIN_LABELS)
        self.assertEqual(kinds["prompt"], PROMPTS)
        self.assertEqual(kinds["template"], TEMPLATES)
        self.assertEqual(kinds["theme"], LIGHT | DARK | HYBRID)
        pairs = [(item["kind"], item["id"]) for item in index["items"]]
        self.assertEqual(pairs, sorted(pairs))

        by_id = {item["id"]: item for item in index["items"]}
        for item_id in LIGHT:
            preview = by_id[item_id]["preview"]
            self.assertFalse(preview["dark"])
            self.assertNotIn("page", preview)
        for item_id in DARK:
            preview = by_id[item_id]["preview"]
            self.assertTrue(preview["dark"])
            self.assertNotIn("page", preview)
        for item_id in HYBRID:
            preview = by_id[item_id]["preview"]
            self.assertTrue(preview["dark"])
            self.assertEqual(list(preview["page"]), ["background", "text", "accent"])
            self.assertGreater(build_index.relative_luminance(preview["page"]["background"]), 0.5)

        for item_id in TEMPLATES:
            path = root / "templates" / f"{item_id}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(_sentence_count(data["body"]), 2)
            self.assertLessEqual(_sentence_count(data["body"]), 5)
            self.assertEqual(by_id[item_id]["preview"]["subject"], data["subject"])
            self.assertEqual(by_id[item_id]["preview"]["firstLine"], data["body"].splitlines()[0])
            names = [match.group(1).strip() for match in build_index.PLACEHOLDER_RE.finditer(data["subject"] + "\n" + data["body"])]
            self.assertTrue(names)
            self.assertTrue(set(names) <= build_index.KNOWN_PLACEHOLDERS)

        scanned = [
            root / "README.md",
            root / "LICENSE",
            root / ".github" / "workflows" / "check.yml",
            root / "tools" / "build_index.py",
            root / "tools" / "test_build_index.py",
            root / "index.json",
        ]
        scanned += sorted((root / "themes").glob("*.json"))
        scanned += sorted((root / "templates").glob("*.json"))
        for path in scanned:
            file_text = path.read_text(encoding="utf-8")
            for char, name in FORBIDDEN.items():
                self.assertNotIn(char, file_text, f"{path} contains an {name}")


def _terminator_count(text):
    return sum(text.count(char) for char in ".!?")


def _sentence_count(body):
    flat = " ".join(line.strip() for line in body.splitlines() if line.strip())
    return len(re.findall(r"[^.!?]+[.!?]", flat))


if __name__ == "__main__":
    unittest.main()
