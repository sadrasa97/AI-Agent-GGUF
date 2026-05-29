"""
Tools for extracting, saving, and running generated code.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────
# Language → file extension map
# ─────────────────────────────────────────────
EXT_MAP: dict[str, str] = {
    "python":     "py",
    "py":         "py",
    "javascript": "js",
    "js":         "js",
    "typescript": "ts",
    "ts":         "ts",
    "bash":       "sh",
    "sh":         "sh",
    "shell":      "sh",
    "zsh":        "sh",
    "rust":       "rs",
    "go":         "go",
    "java":       "java",
    "c":          "c",
    "cpp":        "cpp",
    "c++":        "cpp",
    "csharp":     "cs",
    "cs":         "cs",
    "ruby":       "rb",
    "rb":         "rb",
    "php":        "php",
    "swift":      "swift",
    "kotlin":     "kt",
    "html":       "html",
    "css":        "css",
    "json":       "json",
    "yaml":       "yaml",
    "yml":        "yml",
    "sql":        "sql",
    "r":          "r",
    "dart":       "dart",
    "lua":        "lua",
    "perl":       "pl",
    "scala":      "scala",
}

# ─────────────────────────────────────────────
# Runner map  (lang → how to run a file)
# ─────────────────────────────────────────────
RUNNER_MAP: dict[str, list[str]] = {
    "py":   ["python3", "{file}"],
    "js":   ["node", "{file}"],
    "ts":   ["npx", "ts-node", "{file}"],
    "sh":   ["bash", "{file}"],
    "rb":   ["ruby", "{file}"],
    "php":  ["php", "{file}"],
    "go":   ["go", "run", "{file}"],
    "lua":  ["lua", "{file}"],
    "pl":   ["perl", "{file}"],
    "r":    ["Rscript", "{file}"],
}

TEXT_EXTENSIONS = {
    "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml", "md",
    "txt", "cfg", "ini", "env", "sh", "bat", "ps1", "rs", "go", "java",
    "c", "cpp", "h", "hpp", "cs", "rb", "php", "swift", "kt", "html",
    "css", "sql", "lua", "pl", "r", "dart", "xml", "svg",
}

IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "dist", "build"}

DEFAULT_MAX_TREE_FILES = 120
DEFAULT_MAX_FILE_BYTES = 8000
DEFAULT_MAX_DEPTH = 4


class CodeBlock:
    """Represents a single extracted code block."""

    def __init__(self, language: str, code: str):
        self.language = language.lower().strip()
        self.code = code.strip()

    @property
    def extension(self) -> str:
        return EXT_MAP.get(self.language, "txt")

    def __repr__(self):
        lines = self.code.count("\n") + 1
        return f"<CodeBlock lang={self.language!r} lines={lines}>"


def _is_within_workspace(workspace: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(workspace.resolve())
        return True
    except Exception:
        return False


def resolve_workspace_path(workspace: Path, target: str) -> Path:
    """
    Resolve a user-provided path against the workspace and block path escapes.
    """
    raw_target = Path(target).expanduser()
    candidate = raw_target.resolve() if raw_target.is_absolute() else (workspace / raw_target).resolve()
    if not _is_within_workspace(workspace, candidate):
        raise ValueError(f"Path escapes workspace: {target}")
    return candidate


def workspace_tree_text(
    workspace: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_TREE_FILES,
) -> str:
    files = list_workspace_files(workspace, max_depth=max_depth, max_files=max_files)
    lines = [f"Workspace root: {workspace.resolve()}", "Workspace tree:"]
    if not files:
        lines.append("  (workspace is empty)")
    else:
        for path in files:
            lines.append(f"  - {path.relative_to(workspace).as_posix()}")
        if len(files) >= max_files:
            lines.append(f"  ... (showing first {max_files} files only)")
    return "\n".join(lines)


def _normalize_query(text: str) -> str:
    text = text.strip().strip("\"'“”‘’[](){}")
    text = text.replace("\\", "/")
    return text.lower()


def _candidate_queries(user_text: str) -> list[str]:
    queries: list[str] = []

    # Explicit path-like tokens, with or without quotes.
    pattern = re.compile(
        r'(?:"|\'|`)?((?:[A-Za-z]:)?[\\/][^ \n\t\r"\'`]+|[^ \n\t\r"\'`]+\.[A-Za-z0-9_+-]+)(?:"|\'|`)?'
    )
    for match in pattern.finditer(user_text):
        query = _normalize_query(match.group(1))
        if query:
            queries.append(query)

    lowered = user_text.lower()
    for token in re.findall(r"[A-Za-z0-9_.\-\\/]+", lowered):
        if "." in token or token in {"readme", "license", "changelog", "todo"}:
            queries.append(_normalize_query(token))

    # Common alias mapping for README requests.
    if "readme" in lowered and "readme" not in queries:
        queries.append("readme")

    seen: set[str] = set()
    deduped: list[str] = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def _match_workspace_file(workspace: Path, query: str, files: list[Path]) -> Optional[Path]:
    workspace = workspace.resolve()
    query = _normalize_query(query)
    if not query:
        return None

    candidate = Path(query.replace("/", "\\"))
    if candidate.is_absolute():
        try:
            resolved = resolve_workspace_path(workspace, str(candidate))
        except ValueError:
            resolved = None
        else:
            if resolved.exists() and resolved.is_file():
                return resolved

    normalized_files: list[tuple[Path, str, str]] = []
    for path in files:
        rel = path.relative_to(workspace).as_posix().lower()
        normalized_files.append((path, rel, path.name.lower()))

    # Exact relative path match first.
    for path, rel, _ in normalized_files:
        if rel == query:
            return path

    # Then basename or suffix match.
    query_name = Path(query).name
    query_stem = Path(query_name).stem
    query_suffix = Path(query_name).suffix.lower()
    for path, rel, name in normalized_files:
        stem = Path(name).stem
        if name == query_name:
            return path
        if query_suffix and rel.endswith(query):
            return path
        if stem == query_stem and query_stem:
            return path

    # README / readme fallback.
    if query in {"readme", "readme.md"}:
        for path, _, name in normalized_files:
            if name.startswith("readme"):
                return path

    # Substring fallback for partial names like "main" or "config".
    for path, rel, name in normalized_files:
        if query in name or query in rel:
            return path
    return None


def resolve_workspace_file_queries(workspace: Path, user_text: str) -> list[Path]:
    workspace = workspace.resolve()
    files = list_workspace_files(workspace)
    queries = _candidate_queries(user_text)
    resolved: list[Path] = []
    seen: set[Path] = set()
    for query in queries:
        match = _match_workspace_file(workspace, query, files)
        if match and match not in seen:
            seen.add(match)
            resolved.append(match)
    return resolved


def list_workspace_files(
    workspace: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_TREE_FILES,
) -> list[Path]:
    files: list[Path] = []
    workspace = workspace.resolve()
    for path in workspace.rglob("*"):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            continue
        if len(rel.parts) > max_depth:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files)


def read_text_file(path: Path, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> str:
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
        return data.decode("utf-8", errors="replace") + "\n\n[truncated]"
    return data.decode("utf-8", errors="replace")


def build_workspace_context(
    workspace: Path,
    user_text: Optional[str] = None,
    recent_files: Optional[list[Path]] = None,
    max_files: int = DEFAULT_MAX_TREE_FILES,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> str:
    """
    Build a compact workspace snapshot for the model prompt.
    Includes a file tree plus contents of recently opened files.
    """
    workspace = workspace.resolve()
    recent_files = recent_files or []
    all_files = list_workspace_files(workspace, max_depth=max_depth, max_files=max_files)
    requested_files = resolve_workspace_file_queries(workspace, user_text or "") if user_text else []
    requested_set = {path.resolve() for path in requested_files}

    recent_unique: list[Path] = []
    seen: set[Path] = set()
    for path in recent_files:
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            continue
        if resolved in seen:
            continue
        if not _is_within_workspace(workspace, resolved):
            continue
        if not resolved.is_file():
            continue
        seen.add(resolved)
        recent_unique.append(resolved)

    lines: list[str] = [workspace_tree_text(workspace, max_depth=max_depth, max_files=max_files)]

    if requested_files:
        lines.append("")
        lines.append("Requested files:")
        for path in requested_files:
            rel = path.relative_to(workspace)
            lines.append(f"  - {rel.as_posix()}")
            try:
                content = read_text_file(path, max_bytes=max_bytes)
            except Exception as exc:
                lines.append(f"    [unable to read: {exc}]")
                continue
            indented = "\n".join(f"    {line}" for line in content.splitlines())
            lines.append(indented if indented else "    (empty file)")

    recent_files_to_include = [path for path in recent_unique if path.resolve() not in requested_set]
    if recent_files_to_include:
        lines.append("")
        lines.append("Recently opened files:")
        for path in recent_files_to_include[-5:]:
            rel = path.relative_to(workspace)
            suffix = path.suffix.lstrip(".").lower()
            if suffix and suffix not in TEXT_EXTENSIONS:
                lines.append(f"  - {rel.as_posix()} (binary or unsupported, not shown)")
                continue
            lines.append(f"  - {rel.as_posix()}")
            try:
                content = read_text_file(path, max_bytes=max_bytes)
            except Exception as exc:
                lines.append(f"    [unable to read: {exc}]")
                continue
            indented = "\n".join(f"    {line}" for line in content.splitlines())
            lines.append(indented if indented else "    (empty file)")

    lines.append("")
    lines.append(
        "Instructions: use the workspace tree and any requested file contents above when answering. "
        "If the user mentions a file name, try to resolve it from the workspace automatically."
    )
    return "\n".join(lines)


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """
    Pull all fenced code blocks from model output.
    Handles both  ```python  and  ``` (no lang tag).
    """
    pattern = re.compile(
        r"```(?P<lang>[a-zA-Z0-9+#_-]*)\n(?P<code>.*?)```",
        re.DOTALL,
    )
    blocks = []
    for m in pattern.finditer(text):
        lang = m.group("lang") or "text"
        code = m.group("code")
        blocks.append(CodeBlock(lang, code))
    return blocks


def save_code(
    block: CodeBlock,
    workspace: Path,
    filename: Optional[str] = None,
) -> Path:
    """Save a CodeBlock to disk, return the saved path."""
    if filename:
        out_path = workspace / filename
    else:
        # auto-number files to avoid overwriting
        idx = 1
        while True:
            candidate = workspace / f"output_{idx:03d}.{block.extension}"
            if not candidate.exists():
                out_path = candidate
                break
            idx += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(block.code, encoding="utf-8")
    return out_path


def run_code(path: Path) -> tuple[int, str, str]:
    """
    Execute a saved code file. Returns (returncode, stdout, stderr).
    Only languages with a registered runner are executed.
    """
    ext = path.suffix.lstrip(".")
    runner_template = RUNNER_MAP.get(ext)
    if not runner_template:
        return -1, "", f"No runner registered for .{ext} files."

    cmd = [c.replace("{file}", str(path)) for c in runner_template]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", "⏱️  Execution timed out (30 s)."
