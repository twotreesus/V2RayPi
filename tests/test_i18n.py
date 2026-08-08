import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'templates'
TEMPLATES = tuple(TEMPLATE_DIR.glob('*.html'))
KEY = r'[a-z][a-z0-9_.-]+'
REGISTERED = re.compile(
    r'["\'](' + KEY + r')["\']\s*:\s*\{\s*zh\s*:',
    re.DOTALL,
)
DATA_REFERENCE = re.compile(
    r'data-i18n(?:-[a-z-]+)?=["\'](' + KEY + r')["\']',
)
FUNCTION_REFERENCE = re.compile(
    r'\bt\(\s*["\'](' + KEY + r')["\']',
)
API_ERROR_REFERENCE = re.compile(
    r'I18n\.apiError\([^;]*?["\'](' + KEY + r')["\']\s*\)',
    re.DOTALL,
)
COMPLETE_ENTRY = re.compile(
    r'["\'](' + KEY + r')["\']\s*:\s*\{\s*'
    r'zh\s*:\s*"(?:\\.|[^"\\])*"\s*,\s*'
    r'en\s*:\s*"(?:\\.|[^"\\])*"\s*\}',
    re.DOTALL,
)
DYNAMIC_CHINESE = re.compile(
    r'(?:message|pop_toast|update_toast|mdui\.confirm|mdui\.prompt)'
    r'\([^\n]*(?:["\'][^"\']*[\u4e00-\u9fff])',
)


class VisibleChineseParser(HTMLParser):
    VOID_ELEMENTS = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }

    def __init__(self):
        super().__init__()
        self.stack = []
        self.untranslated = []

    def handle_starttag(self, tag, attrs):
        self.stack.append((tag, dict(attrs)))
        if tag in self.VOID_ELEMENTS:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data):
        if not re.search(r'[\u4e00-\u9fff]', data):
            return
        if any(tag in ('script', 'style') for tag, _ in self.stack):
            return
        translated = any(
            any(key.startswith('data-i18n') for key in attrs)
            for _, attrs in self.stack
        )
        if not translated and data.strip():
            self.untranslated.append(data.strip())


class I18nDictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            path.name: path.read_text(encoding='utf-8')
            for path in TEMPLATES
        }
        cls.registered = set()
        cls.complete = set()
        cls.referenced = set()
        for source in cls.sources.values():
            cls.registered.update(REGISTERED.findall(source))
            cls.complete.update(COMPLETE_ENTRY.findall(source))
            cls.referenced.update(DATA_REFERENCE.findall(source))
            cls.referenced.update(FUNCTION_REFERENCE.findall(source))
            cls.referenced.update(API_ERROR_REFERENCE.findall(source))

    def test_every_reference_has_a_translation(self):
        self.assertEqual(self.referenced - self.registered, set())

    def test_every_translation_has_chinese_and_english_text(self):
        self.assertEqual(self.registered - self.complete, set())

    def test_each_page_uses_its_own_key_namespace(self):
        expected_prefixes = {
            'status.html': 'status.',
            'subscribe.html': 'subscribe.',
            'advance.html': 'advance.',
            'system.html': 'system.',
        }
        for filename, prefix in expected_prefixes.items():
            keys = set(REGISTERED.findall(self.sources[filename]))
            self.assertTrue(keys)
            self.assertTrue(all(key.startswith(prefix) for key in keys))

    def test_visible_chinese_fallbacks_are_marked_for_translation(self):
        untranslated = {}
        for filename, source in self.sources.items():
            parser = VisibleChineseParser()
            parser.feed(source)
            if parser.untranslated:
                untranslated[filename] = parser.untranslated
        self.assertEqual(untranslated, {})

    def test_dynamic_messages_do_not_bypass_translation(self):
        bypasses = {
            filename: DYNAMIC_CHINESE.findall(source)
            for filename, source in self.sources.items()
            if DYNAMIC_CHINESE.search(source)
        }
        self.assertEqual(bypasses, {})


if __name__ == '__main__':
    unittest.main()
