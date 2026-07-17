"""Lightweight, offline hover-documentation lookup.

Not a full language server — just a curated dictionary of the most
common Python / JavaScript builtins, keywords, and well-known library
names, so the editor can show a short VS-Code-style tooltip when the
user hovers the mouse over a recognized word. Anything not in the
dictionary simply shows no tooltip (same as VS Code without a
language server attached).
"""
from __future__ import annotations

PYTHON_DOCS: dict[str, str] = {
    "print": "print(*values, sep=' ', end='\\n') — write values to stdout.",
    "len": "len(obj) — return the number of items in a container.",
    "range": "range(stop) / range(start, stop, step) — arithmetic sequence of ints.",
    "list": "list(iterable) — build a mutable, ordered sequence.",
    "dict": "dict(**kwargs) — build a mutable mapping of key/value pairs.",
    "set": "set(iterable) — build an unordered collection of unique items.",
    "tuple": "tuple(iterable) — build an immutable, ordered sequence.",
    "str": "str(object) — convert to a string / the text type.",
    "int": "int(x) — convert to an integer.",
    "float": "float(x) — convert to a floating point number.",
    "bool": "bool(x) — convert to True/False.",
    "open": "open(file, mode='r') — open a file and return a file object.",
    "enumerate": "enumerate(iterable, start=0) — yield (index, value) pairs.",
    "zip": "zip(*iterables) — pair up items from multiple iterables.",
    "map": "map(func, iterable) — apply func to every item, lazily.",
    "filter": "filter(func, iterable) — keep items where func(item) is truthy.",
    "sorted": "sorted(iterable, key=None, reverse=False) — return a new sorted list.",
    "isinstance": "isinstance(obj, cls) — check if obj is an instance of cls.",
    "super": "super() — proxy to a parent/sibling class's methods (used in __init__).",
    "self": "Conventional name for the instance in an instance method.",
    "cls": "Conventional name for the class in a classmethod.",
    "lambda": "lambda args: expr — inline anonymous function.",
    "yield": "Pause a generator function and produce a value to the caller.",
    "async": "Declare a coroutine function usable with 'await'.",
    "await": "Suspend a coroutine until an awaitable result is ready.",
    "with": "Context manager block — calls __enter__/__exit__ automatically.",
    "try": "Begin a try/except block for handling exceptions.",
    "except": "Catch exceptions raised in the preceding try block.",
    "finally": "Code that always runs after try/except, success or failure.",
    "raise": "Raise (throw) an exception.",
    "assert": "assert condition, msg — raise AssertionError if condition is False.",
    "None": "The singleton representing 'no value'.",
    "True": "Boolean true value.",
    "False": "Boolean false value.",
    "def": "Define a function.",
    "class": "Define a class.",
    "import": "Import a module or package.",
    "from": "Import specific names from a module (from X import Y).",
    "return": "Exit a function, optionally returning a value.",
    "os": "Standard library — operating system interfaces (paths, env vars, processes).",
    "sys": "Standard library — interpreter internals (argv, path, stdout/stderr, exit).",
    "re": "Standard library — regular expressions.",
    "json": "Standard library — encode/decode JSON.",
    "pathlib": "Standard library — object-oriented filesystem paths (Path).",
    "Path": "pathlib.Path — object-oriented filesystem path.",
    "datetime": "Standard library — date/time types and arithmetic.",
    "typing": "Standard library — type hints (Optional, List, Dict, Union, ...).",
    "asyncio": "Standard library — asynchronous I/O / coroutine event loop.",
    "collections": "Standard library — specialized containers (deque, Counter, defaultdict, ...).",
    "itertools": "Standard library — fast, memory-efficient iterator building blocks.",
    "functools": "Standard library — higher-order functions (reduce, lru_cache, partial, ...).",
    "subprocess": "Standard library — spawn and manage child processes.",
    "logging": "Standard library — configurable logging framework.",
    "numpy": "Third-party — N-dimensional array computing (np).",
    "pandas": "Third-party — tabular data analysis (DataFrame/Series).",
    "torch": "Third-party — PyTorch, tensor computation & deep learning.",
    "tensorflow": "Third-party — deep learning framework (Google).",
    "transformers": "Third-party (Hugging Face) — pretrained NLP/vision transformer models.",
    "requests": "Third-party — simple HTTP client library.",
    "flask": "Third-party — lightweight web application framework.",
    "fastapi": "Third-party — modern async web API framework with type-based validation.",
    "pydantic": "Third-party — data validation using Python type annotations.",
    "sklearn": "Third-party (scikit-learn) — classical machine learning toolkit.",
    "matplotlib": "Third-party — 2D plotting library.",
    "PySide6": "Third-party — official Qt for Python bindings (GUI toolkit).",
    "PyQt6": "Third-party — Qt for Python bindings (GUI toolkit).",
}

JS_DOCS: dict[str, str] = {
    "console": "console.log/warn/error(...) — print to the developer console.",
    "function": "Declare a function.",
    "const": "Declare a block-scoped variable that cannot be reassigned.",
    "let": "Declare a block-scoped, reassignable variable.",
    "var": "Declare a function-scoped variable (legacy — prefer let/const).",
    "class": "Define a class.",
    "async": "Declare an asynchronous function that returns a Promise.",
    "await": "Pause execution until a Promise settles (inside an async function).",
    "Promise": "Represents the eventual result of an asynchronous operation.",
    "fetch": "fetch(url, options) — make an HTTP request, returns a Promise<Response>.",
    "map": "Array.prototype.map(fn) — build a new array by transforming each item.",
    "filter": "Array.prototype.filter(fn) — keep items where fn(item) is truthy.",
    "reduce": "Array.prototype.reduce(fn, init) — fold an array down to a single value.",
    "this": "Reference to the current execution context / owning object.",
    "JSON": "Global object — JSON.stringify()/JSON.parse() for JSON conversion.",
    "React": "Third-party — declarative UI library based on components.",
    "useState": "React hook — declare local component state.",
    "useEffect": "React hook — run side effects after render.",
    "express": "Third-party (Node.js) — minimal web application framework.",
}

# Case/extension aware dispatch table.
_TABLES = {
    "py": PYTHON_DOCS,
    "js": JS_DOCS,
    "jsx": JS_DOCS,
    "ts": JS_DOCS,
    "tsx": JS_DOCS,
}


def lookup_hover_doc(word: str, extension: str) -> str | None:
    """Return a short hover doc string for `word` given the file
    `extension`, or None if nothing is known about it."""
    if not word:
        return None
    table = _TABLES.get((extension or "").lower())
    if table is None:
        # Fall back to Python docs for unknown/generic extensions since
        # most builtins names (print, len, ...) are still informative.
        table = PYTHON_DOCS
    return table.get(word)