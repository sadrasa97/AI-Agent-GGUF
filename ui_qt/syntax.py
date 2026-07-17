"""
State-of-the-art lightweight syntax highlighter with an ultra-premium dark theme palette.
Optimized for rapid structural regex evaluation across common development languages.
"""
from __future__ import annotations

import re
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

# State-of-the-art Deep Dark Premium Palette
C_KEYWORD = QColor("#ff757f")     # Elegant Soft Red / Pink Accent
C_BUILTIN = QColor("#7ad9ff")     # Ice Cyan for core types/builtins
C_STRING = QColor("#9ece6a")      # Calming Sage Green
C_COMMENT = QColor("#565f89")     # Subdued Slate Grey-Blue
C_NUMBER = QColor("#ff9e64")      # Warm Amber Orange
C_FUNC = QColor("#7aa2f7")        # Vibrant Deep Sky Blue
C_CLASS = QColor("#e0af68")       # Bright Warm Ochre Gold
C_DECORATOR = QColor("#bb9af7")   # Vivid Electric Purple
C_SELF = QColor("#2ac3de")        # Bright Teal Accent
C_OPERATOR = QColor("#89ddff")    # Light Aqua for brackets/symbols

PY_KEYWORDS = [
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield", "match", "case",
]

JS_KEYWORDS = [
    "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally",
    "for", "function", "if", "import", "in", "instanceof", "let", "new",
    "return", "super", "switch", "this", "throw", "try", "typeof", "var",
    "void", "while", "with", "yield", "async", "await", "of", "static",
]

GENERIC_KEYWORDS = [
    "if", "else", "for", "while", "return", "break", "continue", "switch",
    "case", "default", "class", "struct", "public", "private", "protected",
    "static", "void", "int", "float", "double", "char", "bool", "const",
    "namespace", "using", "include", "template", "typename", "new", "delete",
]

EXT_KEYWORDS = {
    "py": PY_KEYWORDS,
    "js": JS_KEYWORDS,
    "jsx": JS_KEYWORDS,
    "ts": JS_KEYWORDS,
    "tsx": JS_KEYWORDS,
}


def _fmt(color: QColor, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(color)
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


class CodeHighlighter(QSyntaxHighlighter):
    """A highly expressive, fast code tokenizer using targeted regular expressions."""

    def __init__(self, document, extension: str = "py"):
        super().__init__(document)
        self.extension = extension
        self._build_rules()

    def set_extension(self, extension: str):
        if extension != self.extension:
            self.extension = extension
            self._build_rules()
            self.rehighlight()

    def _build_rules(self):
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        keywords = EXT_KEYWORDS.get(self.extension, GENERIC_KEYWORDS)

        # 1. Keywords
        kw_fmt = _fmt(C_KEYWORD, bold=True)
        for kw in keywords:
            pattern = QRegularExpression(rf"\b{re.escape(kw)}\b")
            self.rules.append((pattern, kw_fmt))

        # 2. PySide/Core Object Reference shortcuts
        self.rules.append((QRegularExpression(r"\b(self|cls|this|super)\b"), _fmt(C_SELF, italic=True)))

        # 3. Modern Operators & Punctuation
        self.rules.append((QRegularExpression(r"[-+*/%=<>!&|^~]"), _fmt(C_OPERATOR)))

        # 4. Decorators / Annotations
        self.rules.append((QRegularExpression(r"@\w+"), _fmt(C_DECORATOR)))

        # 5. Functions & Method Names
        self.rules.append((QRegularExpression(r"\bdef\s+(\w+)"), _fmt(C_FUNC, bold=True)))
        self.rules.append((QRegularExpression(r"\bfunction\s+(\w+)"), _fmt(C_FUNC, bold=True)))
        self.rules.append((QRegularExpression(r"\b(\w+)(?=\s*\()"), _fmt(C_FUNC)))

        # 6. Structs & Class Defs
        self.rules.append((QRegularExpression(r"\bclass\s+(\w+)"), _fmt(C_CLASS, bold=True)))

        # 7. Numeric Constants
        self.rules.append((QRegularExpression(r"\b[0-9]+\.?[0-9]*\b"), _fmt(C_NUMBER)))

        # 8. Text Strings
        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), _fmt(C_STRING)))
        self.rules.append((QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), _fmt(C_STRING)))

        # 9. Line Comments
        if self.extension in ("py",):
            self.comment_rule = QRegularExpression(r"#.*")
        elif self.extension in ("js", "ts", "jsx", "tsx", "c", "cpp", "cs", "java", "go", "rs"):
            self.comment_rule = QRegularExpression(r"//.*")
        else:
            self.comment_rule = None

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        if self.comment_rule is not None:
            it = self.comment_rule.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), _fmt(C_COMMENT, italic=True))