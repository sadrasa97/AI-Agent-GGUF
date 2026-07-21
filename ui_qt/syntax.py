"""VS-Code-style syntax highlighter with markdown support."""
from __future__ import annotations
import re
import keyword
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

# Markdown-specific colors
C_BOLD = QColor("#ff757f")        # Same as keywords
C_ITALIC = QColor("#9ece6a")      # Same as strings
C_LINK = QColor("#7ad9ff")        # Same as builtins

# Keywords for different languages
PY_KEYWORDS = keyword.kwlist
JS_KEYWORDS = [
    "break", "case", "catch", "class", "const", "continue", "debugger", "default",
    "delete", "do", "else", "export", "extends", "finally", "for", "function", "if",
    "import", "in", "instanceof", "let", "new", "return", "super", "switch", "this",
    "throw", "try", "typeof", "var", "void", "while", "with", "yield", "async", "await",
    "enum", "implements", "interface", "package", "private", "protected", "public", "static",
    "null", "true", "false",
]
GENERIC_KEYWORDS = [
    "if", "else", "for", "while", "return", "class", "struct", "enum", "import", "from",
    "switch", "case", "break", "continue", "try", "catch", "finally", "throw", "new", "const",
    "let", "var", "public", "private", "protected", "static", "void", "true", "false", "null",
]

EXT_KEYWORDS = {
    "py": PY_KEYWORDS,
    "js": JS_KEYWORDS,
    "jsx": JS_KEYWORDS,
    "ts": JS_KEYWORDS,
    "tsx": JS_KEYWORDS,
    "md": []  # Markdown doesn't use keywords
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
    """A highly expressive, fast code tokenizer with markdown support."""
    
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
        
        # 10. Markdown-specific rules
        if self.extension == "md":
            # Headings
            self.rules.append((QRegularExpression(r"^#{1,6}\s+.*"), _fmt(C_BOLD, bold=True)))
            
            # Bold
            self.rules.append((QRegularExpression(r"\*\*(.*?)\*\*"), _fmt(C_BOLD)))
            
            # Italics
            self.rules.append((QRegularExpression(r"\*(.*?)\*"), _fmt(C_ITALIC)))
            
            # Links
            self.rules.append((QRegularExpression(r"\[(.*?)\]\((.*?)\)"), _fmt(C_LINK)))
    
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