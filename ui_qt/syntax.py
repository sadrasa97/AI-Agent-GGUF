"""
Regex-based syntax highlighter — good enough for a VS-Code-like *feel*
without pulling in a full tree-sitter/pygments dependency.
Supports Python, JS/TS, JSON, and a generic C-like fallback, selected by
file extension.
"""
from __future__ import annotations

import re
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

# VS Code "Dark+" inspired palette
C_KEYWORD = QColor("#569CD6")
C_STRING = QColor("#CE9178")
C_COMMENT = QColor("#6A9955")
C_NUMBER = QColor("#B5CEA8")
C_FUNC = QColor("#DCDCAA")
C_CLASS = QColor("#4EC9B0")
C_DECORATOR = QColor("#D7BA7D")
C_SELF = QColor("#569CD6")

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
    """A single highlighter instance whose rules are rebuilt when the
    associated tab's file extension changes."""

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

        kw_fmt = _fmt(C_KEYWORD, bold=True)
        for kw in keywords:
            pattern = QRegularExpression(rf"\b{re.escape(kw)}\b")
            self.rules.append((pattern, kw_fmt))

        # decorators (python)
        self.rules.append((QRegularExpression(r"@\w+"), _fmt(C_DECORATOR)))

        # function / class defs
        self.rules.append(
            (QRegularExpression(r"\bdef\s+(\w+)"), _fmt(C_FUNC))
        )
        self.rules.append(
            (QRegularExpression(r"\bclass\s+(\w+)"), _fmt(C_CLASS, bold=True))
        )
        self.rules.append((QRegularExpression(r"\bself\b"), _fmt(C_SELF, italic=True)))
        self.rules.append((QRegularExpression(r"\bfunction\s+(\w+)"), _fmt(C_FUNC)))

        # numbers
        self.rules.append((QRegularExpression(r"\b[0-9]+\.?[0-9]*\b"), _fmt(C_NUMBER)))

        # strings
        self.rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), _fmt(C_STRING)))
        self.rules.append((QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), _fmt(C_STRING)))

        # comments
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
