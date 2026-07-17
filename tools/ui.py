"""
Terminal UI helpers: banners, syntax-highlighted code output, spinners.
Uses 'rich' if available, falls back to plain ANSI otherwise.
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from typing import Optional

# ─── Try to import rich ──────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich.text import Text
    from rich.rule import Rule
    from rich import print as rprint
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None  # type: ignore


# ─── ANSI fallback colors ────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
GREY   = "\033[90m"
BLUE   = "\033[34m"
MAGENTA= "\033[35m"


def banner(model_name: str, workspace: str):
    art = r"""
     ██████╗  ██████╗ ██╗   ██╗███████╗     █████╗  ██████╗ ███████╗███╗   ██╗████████╗
    ██╔════╝ ██╔═══██╗██║   ██║██╔════╝    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
    ██║  ███╗██║   ██║██║   ██║█████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
    ██║   ██║██║   ██║██║   ██║██╔══╝      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
    ╚██████╔╝╚██████╔╝╚██████╔╝██║         ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
     ╚═════╝  ╚═════╝  ╚═════╝ ╚═╝         ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
    
    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │                           Nova Code Agent                                       │
    │                 Local AI Coding Assistant powered by GGUF                       │
    ├─────────────────────────────────────────────────────────────────────────────────┤
    │ Backend      : llama.cpp / llama-cpp-python                                     │
    │ Models       : Qwen · DeepSeek · Mistral · Phi · CodeLlama · Llama              │
    │ Workspace    : Workspace-aware development environment                           │
    │ Features     : Chat · Generate · Refactor · Explain · Execute                   │
    │ Execution    : Local & Offline                                                   │
    └─────────────────────────────────────────────────────────────────────────────────┘
    
    Type /help to view available commands.
    """
    if HAS_RICH:
        console.print(art, style="bold cyan")
        console.print(
            Panel.fit(
                f"[bold green]Model:[/bold green] {model_name}\n"
                f"[bold blue]Workspace:[/bold blue] {workspace}",
                title="[bold]Nova Code Agent[/bold]",
                border_style="cyan",
            )
        )
    else:
        print(f"{CYAN}{art}{RESET}")
        print(f"{BOLD}  Model    :{RESET} {GREEN}{model_name}{RESET}")
        print(f"{BOLD}  Workspace:{RESET} {BLUE}{workspace}{RESET}")
    print()


def print_help():
    commands = [
        ("/help",         "Show this help message"),
        ("/save [name]",  "Save last code block to workspace"),
        ("/run",          "Save & run the last code block"),
        ("/show",         "Re-display the last response"),
        ("/history",      "Print conversation history"),
        ("/clear",        "Clear conversation history"),
        ("/multi",        "Enter multi-line input mode (end with ;;)"),
        ("/tree",         "Show workspace file tree"),
        ("/open <path>",  "Open a workspace file and add it to context"),
        ("/regex <pattern>", "Search project files with a regex"),
        ("/ps <command>", "Run a PowerShell command in the workspace"),
        ("ask about main.py", "Files mentioned in your prompt are loaded automatically"),
        ("/workspace",    "Open workspace folder in VS Code"),
        ("/exit",         "Quit the agent"),
    ]
    if HAS_RICH:
        from rich.table import Table
        t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        t.add_column("Command",     style="cyan",  no_wrap=True)
        t.add_column("Description", style="white")
        for cmd, desc in commands:
            t.add_row(cmd, desc)
        console.print(t)
    else:
        print(f"{BOLD}Commands:{RESET}")
        for cmd, desc in commands:
            print(f"  {CYAN}{cmd:<22}{RESET} {desc}")


def print_response(text: str, streaming: bool = False):
    """Pretty-print a full model response (after streaming finishes)."""
    if not streaming:
        if HAS_RICH:
            console.print(Rule(style="dim"))
        else:
            print(f"\n{GREY}{'─'*60}{RESET}")


def print_code_block(code: str, language: str, path: Optional[Path] = None):
    label = f"  Saved → {path}" if path else ""
    if HAS_RICH:
        title = f"[bold]{language.upper()}[/bold]{(' · ' + str(path)) if path else ''}"
        syn = Syntax(code, language, theme="monokai", line_numbers=True)
        console.print(Panel(syn, title=title, border_style="green"))
    else:
        print(f"\n{GREEN}┌── {language.upper()}{label} ──{RESET}")
        for i, line in enumerate(code.splitlines(), 1):
            print(f"{GREY}{i:4d}{RESET}  {line}")
        print(f"{GREEN}└{'─'*40}{RESET}\n")


def print_run_result(returncode: int, stdout: str, stderr: str):
    if HAS_RICH:
        if returncode == 0:
            console.print(Panel(stdout or "(no output)", title="✅ Output", border_style="green"))
        else:
            console.print(Panel(stderr or stdout or "(no output)", title=f"❌ Error (exit {returncode})", border_style="red"))
    else:
        if returncode == 0:
            print(f"{GREEN}▶ Output:{RESET}\n{stdout or '(no output)'}")
        else:
            print(f"{RED}✗ Error (exit {returncode}):{RESET}\n{stderr or stdout or '(no output)'}")


def print_info(msg: str):
    if HAS_RICH:
        console.print(f"[bold cyan]ℹ[/bold cyan]  {msg}")
    else:
        print(f"{CYAN}ℹ  {msg}{RESET}")


def print_success(msg: str):
    if HAS_RICH:
        console.print(f"[bold green]✔[/bold green]  {msg}")
    else:
        print(f"{GREEN}✔  {msg}{RESET}")


def print_error(msg: str):
    if HAS_RICH:
        console.print(f"[bold red]✖[/bold red]  {msg}")
    else:
        print(f"{RED}✖  {msg}{RESET}", file=sys.stderr)


def prompt_user(session_num: int) -> str:
    """Show a styled prompt and return user input."""
    if HAS_RICH:
        console.print(f"\n[bold magenta]❯[/bold magenta] [dim]#{session_num}[/dim] ", end="")
        return input()
    else:
        return input(f"\n{MAGENTA}❯{RESET} {GREY}#{session_num}{RESET} ")


# ─── Spinner ─────────────────────────────────────────────────────────

class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, msg: str = "Thinking…"):
        self.msg = msg
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{CYAN}{frame}{RESET}  {self.msg}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * (len(self.msg) + 6) + "\r")
        sys.stdout.flush()
