"""
CodeAgentREPL — the interactive read-eval-print loop.
Ties together the LLM engine, tool calls, and terminal UI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from config.settings import Settings
from agent.llm_engine import LLMEngine
from tools.code_tools import (
    extract_code_blocks,
    save_code,
    run_code,
    CodeBlock,
    build_workspace_context,
    list_workspace_files,
    read_text_file,
    resolve_workspace_file_queries,
    resolve_workspace_path,
    workspace_tree_text,
)
from tools.ui import (
    banner, print_help, print_code_block, print_run_result,
    print_info, print_success, print_error, prompt_user, Spinner,
    HAS_RICH, RESET, CYAN, BOLD, GREY,
)

try:
    from rich.console import Console
    console = Console()
except ImportError:
    console = None  # type: ignore


class CodeAgentREPL:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = LLMEngine(settings)
        self.history: list[dict] = []      # [{role, content}, …]
        self.last_response: str = ""
        self.last_blocks: list[CodeBlock] = []
        self.recent_files: list[Path] = []
        self._turn = 0

    # ──────────────────────────────────────────────────────────────────
    # Entry point
    # ──────────────────────────────────────────────────────────────────

    def run(self):
        banner(self.settings.model_name, str(self.settings.workspace_path))
        self._print_workspace_tree()
        print_help()
        print()

        while True:
            try:
                user_input = prompt_user(self._turn).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Bye!")
                break

            if not user_input:
                continue

            if user_input == "/multi":
                user_input = self._read_multiline()
                if not user_input:
                    continue

            # slash commands
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            self._chat(user_input)

    # ──────────────────────────────────────────────────────────────────
    # Chat
    # ──────────────────────────────────────────────────────────────────

    def _chat(self, user_text: str):
        self._turn += 1
        self.history.append({"role": "user", "content": user_text})

        # Stream tokens to terminal
        print()
        full_response = ""
        requested_files = resolve_workspace_file_queries(self.settings.workspace_path, user_text)
        if requested_files:
            rel_paths = ", ".join(path.relative_to(self.settings.workspace_path).as_posix() for path in requested_files)
            print_info(f"Auto-loading: {rel_paths}")
        workspace_context = build_workspace_context(
            self.settings.workspace_path,
            user_text=user_text,
            recent_files=self.recent_files,
        )
        try:
            for token in self.engine.stream(self.history, workspace_context=workspace_context):
                print(token, end="", flush=True)
                full_response += token
        except Exception as exc:
            print_error(f"Generation error: {exc}")
            self.history.pop()  # undo the user message on failure
            return

        print("\n")

        self.last_response = full_response
        self.history.append({"role": "assistant", "content": full_response})

        # Auto-extract code blocks and show them nicely
        blocks = extract_code_blocks(full_response)
        self.last_blocks = blocks
        if blocks:
            print_info(f"{len(blocks)} code block(s) found — use /save or /run")

    # ──────────────────────────────────────────────────────────────────
    # Slash commands
    # ──────────────────────────────────────────────────────────────────

    def _handle_command(self, raw: str):
        parts = raw.split(maxsplit=1)
        cmd   = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else None

        dispatch = {
            "/help":      self._cmd_help,
            "/save":      lambda: self._cmd_save(arg),
            "/run":       self._cmd_run,
            "/show":      self._cmd_show,
            "/history":   self._cmd_history,
            "/clear":     self._cmd_clear,
            "/multi":     self._cmd_multi,
            "/tree":      self._cmd_tree,
            "/open":      lambda: self._cmd_open(arg),
            "/cat":       lambda: self._cmd_open(arg),
            "/workspace": self._cmd_workspace,
            "/exit":      self._cmd_exit,
            "/quit":      self._cmd_exit,
        }

        handler = dispatch.get(cmd)
        if handler:
            handler()
        else:
            print_error(f"Unknown command: {cmd}  (type /help)")

    def _cmd_help(self):
        print_help()

    def _cmd_save(self, filename: Optional[str]):
        if not self.last_blocks:
            print_error("No code blocks in last response. Ask the model to write code first.")
            return
        block = self._pick_block()
        path = save_code(block, self.settings.workspace_path, filename)
        print_code_block(block.code, block.language, path)
        print_success(f"Saved → {path}")

    def _cmd_run(self):
        if not self.last_blocks:
            print_error("No code blocks found. Ask the model to write code first.")
            return
        block = self._pick_block()
        path = save_code(block, self.settings.workspace_path)
        print_code_block(block.code, block.language, path)
        print_info(f"Running {path.name} …")
        rc, stdout, stderr = run_code(path)
        print_run_result(rc, stdout, stderr)

    def _cmd_tree(self):
        self._print_workspace_tree()

    def _cmd_open(self, filename: Optional[str]):
        if not filename:
            print_error("Usage: /open relative/path/to/file")
            return

        workspace = self.settings.workspace_path
        try:
            path = resolve_workspace_path(workspace, filename)
        except ValueError as exc:
            print_error(str(exc))
            return

        if not path.exists():
            print_error(f"File not found: {filename}")
            return
        if not path.is_file():
            print_error(f"Not a file: {filename}")
            return

        try:
            content = read_text_file(path)
        except Exception as exc:
            print_error(f"Could not read file: {exc}")
            return

        try:
            self.recent_files.remove(path)
        except ValueError:
            pass
        self.recent_files.append(path)

        rel = path.relative_to(workspace)
        print_success(f"Opened {rel.as_posix()}")
        print()
        print(content)
        print()

    def _cmd_show(self):
        if not self.last_response:
            print_error("No response yet.")
            return
        if HAS_RICH:
            from rich.markdown import Markdown
            console.print(Markdown(self.last_response))
        else:
            print(self.last_response)

    def _cmd_history(self):
        if not self.history:
            print_info("History is empty.")
            return
        for i, msg in enumerate(self.history):
            role  = msg["role"].upper()
            color = CYAN if role == "USER" else GREY
            snippet = msg["content"][:120].replace("\n", " ")
            if len(msg["content"]) > 120:
                snippet += "…"
            print(f"  {color}[{i}] {role}{RESET}: {snippet}")

    def _cmd_clear(self):
        self.history.clear()
        self.last_response = ""
        self.last_blocks = []
        self.recent_files = []
        self._turn = 0
        print_success("History cleared.")

    def _cmd_multi(self):
        text = self._read_multiline()
        if text:
            self._chat(text)

    def _cmd_workspace(self):
        path = str(self.settings.workspace_path.resolve())
        try:
            subprocess.Popen(["code", path])
            print_success(f"Opened {path} in VS Code.")
        except FileNotFoundError:
            print_info(f"VS Code CLI not found. Workspace path: {path}")

    def _cmd_exit(self):
        print("👋 Bye!")
        sys.exit(0)

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _pick_block(self) -> CodeBlock:
        """If multiple blocks, ask user to pick one; otherwise return first."""
        if len(self.last_blocks) == 1:
            return self.last_blocks[0]
        print_info("Multiple code blocks found:")
        for i, b in enumerate(self.last_blocks):
            lines = b.code.count("\n") + 1
            print(f"  [{i}] {b.language:<12} {lines} lines")
        try:
            idx = int(input("  Pick index [0]: ").strip() or "0")
            return self.last_blocks[idx]
        except (ValueError, IndexError):
            return self.last_blocks[0]

    def _read_multiline(self) -> str:
        print_info("Multi-line mode — type your prompt, end with  ;;  on its own line.")
        lines = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip() == ";;":
                break
            lines.append(line)
        return "\n".join(lines).strip()

    def _print_workspace_tree(self):
        print()
        print(workspace_tree_text(self.settings.workspace_path))

