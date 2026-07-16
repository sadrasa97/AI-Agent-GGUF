"""
AgentSession — a small ReAct-style loop that gives any provider (GGUF,
OpenRouter, NVIDIA) real agentic file-system powers: it can search the
workspace, read files, write new files, apply precise edits to existing
files, delete files, and run shell commands — the same class of actions
VS Code's / Copilot's agent mode performs, just driven over plain text
instead of a native function-calling API, so it works uniformly across
every backend.

Protocol: on each turn the model may emit **one** fenced block:

    ```tool_call
    {"name": "read_file", "args": {"path": "src/app.py"}}
    ```

AgentSession executes the tool, feeds the result back as the next
message, and loops (bounded by MAX_ITERATIONS) until the model replies
with plain text instead of a tool call — that plain text is the final
answer and is streamed back to the UI.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

from config.settings import Settings
from tools.code_tools import (
    ToolError,
    agent_delete_file,
    agent_edit_file,
    agent_glob_paths,
    agent_read_file,
    agent_search,
    agent_write_file,
    resolve_workspace_path_from_base,
)

MAX_ITERATIONS = 18
MAX_TOOL_RESULT_CHARS = 12_000

TOOL_CALL_RE = re.compile(r"```tool_call\s*\n(?P<json>.*?)```", re.DOTALL)


class AgentError(RuntimeError):
    pass


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} more chars]"


class AgentSession:
    """Drives the tool-call loop for one user turn in Agent mode."""

    def __init__(self, provider, settings: Settings, on_status: Optional[Callable[[str], None]] = None):
        self.provider = provider
        self.settings = settings
        self.workspace = settings.workspace_path
        self.cwd = self.workspace
        self.on_status = on_status or (lambda _msg: None)
        self.applied_files: list[str] = []  # relative paths written/edited/deleted this turn
        self._validation_needed = False

    def _to_workspace_relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace.resolve()).as_posix()

    def _resolve_from_cwd(self, target: str) -> Path:
        if not target.strip():
            raise ToolError("Path is empty")
        try:
            return resolve_workspace_path_from_base(self.workspace.resolve(), self.cwd.resolve(), target)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------
    def _run_tool(self, name: str, args: dict) -> str:
        name = (name or "").strip().lower()
        try:
            if name in {"search_code", "grep"}:
                query = args.get("query", "")
                is_regex = bool(args.get("is_regex", True))
                if not query:
                    raise ToolError("search_code requires 'query'")
                return agent_search(self.workspace, query, is_regex=is_regex)

            if name == "pwd":
                return self._to_workspace_relative(self.cwd)

            if name == "cd":
                target = args.get("path", ".")
                target_path = self._resolve_from_cwd(target)
                if not target_path.exists():
                    raise ToolError(f"Path not found: {target}")
                if target_path.is_file():
                    target_path = target_path.parent
                if not target_path.is_dir():
                    raise ToolError(f"Not a directory: {target}")
                self.cwd = target_path
                return f"cwd: {self._to_workspace_relative(self.cwd)}"

            if name == "glob":
                pattern = args.get("pattern", "")
                if not pattern:
                    raise ToolError("glob requires 'pattern'")
                return agent_glob_paths(
                    self.workspace,
                    pattern=pattern,
                    cwd=self._to_workspace_relative(self.cwd),
                    include_files=bool(args.get("include_files", True)),
                    include_dirs=bool(args.get("include_dirs", True)),
                    max_results=int(args.get("max_results", 4000)),
                )

            if name in {"list_files", "ls", "dir"}:
                target = str(args.get("path", ".") or ".")
                base = self._resolve_from_cwd(target)
                if base.is_file():
                    base = base.parent
                if not base.exists() or not base.is_dir():
                    raise ToolError(f"Not a directory: {target}")
                rel_base = self._to_workspace_relative(base)
                return agent_glob_paths(
                    self.workspace,
                    pattern="**/*",
                    cwd=rel_base,
                    include_files=True,
                    include_dirs=True,
                    max_results=int(args.get("max_results", 4000)),
                )

            if name == "read_file":
                path = args.get("path", "")
                if not path:
                    raise ToolError("read_file requires 'path'")
                resolved = self._resolve_from_cwd(path)
                return agent_read_file(self.workspace, self._to_workspace_relative(resolved))

            if name == "write_file":
                path = args.get("path", "")
                content = args.get("content", "")
                if not path:
                    raise ToolError("write_file requires 'path'")
                resolved = self._resolve_from_cwd(path)
                rel = self._to_workspace_relative(resolved)
                result = agent_write_file(self.workspace, rel, content, overwrite=bool(args.get("overwrite", True)))
                self.applied_files.append(rel)
                self._validation_needed = True
                return result

            if name == "edit_file":
                path = args.get("path", "")
                old_str = args.get("old_str", "")
                new_str = args.get("new_str", "")
                if not path or not old_str:
                    raise ToolError("edit_file requires 'path' and 'old_str'")
                resolved = self._resolve_from_cwd(path)
                rel = self._to_workspace_relative(resolved)
                result = agent_edit_file(self.workspace, rel, old_str, new_str)
                self.applied_files.append(rel)
                self._validation_needed = True
                return result

            if name == "delete_file":
                path = args.get("path", "")
                if not path:
                    raise ToolError("delete_file requires 'path'")
                resolved = self._resolve_from_cwd(path)
                rel = self._to_workspace_relative(resolved)
                result = agent_delete_file(self.workspace, rel)
                self.applied_files.append(rel)
                self._validation_needed = True
                return result

            if name == "run_command":
                command = args.get("command", "")
                if not command:
                    raise ToolError("run_command requires 'command'")
                return self._run_shell(command)

            return f"[tool error] Unknown tool: {name}"
        except ToolError as exc:
            return f"[tool error] {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"[tool error] {name} failed: {exc}"

    def _run_shell(self, command: str) -> str:
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            try:
                proc = subprocess.run(
                    ["bash", "-lc", command],
                    cwd=str(self.cwd),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except Exception as exc:  # noqa: BLE001
                return f"[shell error] {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"[shell error] {exc}"

        parts = [f"ExitCode: {proc.returncode}"]
        if proc.stdout.strip():
            parts.append("STDOUT:\n" + proc.stdout.strip())
        if proc.stderr.strip():
            parts.append("STDERR:\n" + proc.stderr.strip())
        return _truncate("\n\n".join(parts))

    def _auto_validate_changes(self) -> tuple[bool, str]:
        """Run automatic post-edit validation so the agent can self-correct before final answer."""
        workspace = self.workspace.resolve()

        # Keep only currently existing Python files touched in this turn.
        unique_paths: list[Path] = []
        seen: set[Path] = set()
        for rel in self.applied_files:
            try:
                p = (workspace / rel).resolve()
            except Exception:
                continue
            if p in seen:
                continue
            seen.add(p)
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() != ".py":
                continue
            unique_paths.append(p)

        report_lines: list[str] = []

        if unique_paths:
            cmd = [sys.executable, "-m", "py_compile", *[str(p) for p in unique_paths]]
            compile_result = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=120,
            )
            report_lines.append(f"py_compile exit={compile_result.returncode}")
            if compile_result.stdout.strip():
                report_lines.append("py_compile stdout:\n" + compile_result.stdout.strip())
            if compile_result.stderr.strip():
                report_lines.append("py_compile stderr:\n" + compile_result.stderr.strip())
            if compile_result.returncode != 0:
                return False, "\n\n".join(report_lines)
        else:
            report_lines.append("No Python file changed; py_compile skipped.")

        tests_path = workspace / "tests"
        if tests_path.exists() and tests_path.is_dir():
            try:
                test_result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except Exception as exc:  # noqa: BLE001
                report_lines.append(f"pytest skipped: {exc}")
            else:
                report_lines.append(f"pytest exit={test_result.returncode}")
                if test_result.stdout.strip():
                    report_lines.append("pytest stdout:\n" + test_result.stdout.strip())
                if test_result.stderr.strip():
                    report_lines.append("pytest stderr:\n" + test_result.stderr.strip())
                if test_result.returncode != 0:
                    return False, "\n\n".join(report_lines)

        report_lines.append("Automatic validation passed.")
        return True, "\n\n".join(report_lines)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_tool_call(response: str) -> Optional[tuple[str, dict]]:
        match = TOOL_CALL_RE.search(response)
        if not match:
            return None
        raw = match.group("json").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        name = payload.get("name")
        args = payload.get("args") or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            return None
        return name, args

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self, history: list[dict], workspace_context: Optional[str]) -> Iterator[str]:
        """Yields user-facing text: status lines for each tool step, then the
        final answer's tokens (streamed) once the model stops calling tools."""
        local_history = list(history)

        for iteration in range(MAX_ITERATIONS):
            response = self.provider.complete(local_history, workspace_context=workspace_context, mode="agent")
            call = self._extract_tool_call(response)

            if call is None:
                # If files changed, auto-validate before allowing final answer.
                if self._validation_needed:
                    status = "\n\n> 🧪 **auto_validate**()\n\n"
                    yield status
                    self.on_status("auto_validate()")

                    ok, validation_report = self._auto_validate_changes()
                    self._validation_needed = False if ok else True

                    local_history.append({"role": "assistant", "content": response})
                    local_history.append(
                        {
                            "role": "user",
                            "content": (
                                "Automatic validation result:\n"
                                f"```\n{_truncate(validation_report)}\n```\n\n"
                                + (
                                    "Validation passed. Return the final concise report now (no more tool calls unless strictly needed)."
                                    if ok
                                    else "Validation failed. Continue fixing files using tools, then finish."
                                )
                            ),
                        }
                    )
                    continue

                # Final answer — stream it back token-ish (chunked) to the UI.
                for chunk in _chunk_text(response):
                    yield chunk
                return

            name, args = call
            status = f"\n\n> 🔧 **{name}**({_format_args(args)})\n\n"
            yield status
            self.on_status(f"{name}({_format_args(args)})")

            result = self._run_tool(name, args)
            local_history.append({"role": "assistant", "content": response})
            local_history.append(
                {"role": "user", "content": f"Tool result for `{name}`:\n```\n{_truncate(result)}\n```\n\nContinue."}
            )

        yield (
            "\n\n⚠️ Reached the maximum number of tool steps for this turn "
            "without finishing. Ask me to continue and I'll pick up where I left off."
        )


def _format_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:60] + "…"
        parts.append(f"{k}={v_str!r}")
    return ", ".join(parts)


def _chunk_text(text: str, size: int = 24) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]