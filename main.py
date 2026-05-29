#!/usr/bin/env python3
"""
GGUF Code Agent - Terminal VS Code style agent powered by local GGUF models.
Usage:  python D:\gguf-code-agent\gguf-code-agent\main.py --model "D:\models\Qwen3.5-0.8B-Q4_0.gguf" --workspace "D:\gguf-code-agent\gguf-code-agent"     
"""

import argparse
import sys

from agent.repl import CodeAgentREPL
from config.settings import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GGUF Code Agent - local LLM terminal coding assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Examples:
  python main.py --model "D:\models\Qwen3.5-0.8B-Q4_0.gguf"
  python main.py --model "D:\models\Qwen3.5-0.8B-Q4_0.gguf" --ctx 8192 --threads 8
  python main.py --model "D:\models\Qwen3.5-0.8B-Q4_0.gguf" --workspace ./my_project
        """,
    )
    parser.add_argument(
        "--model", "-m",
        required=True,
        help="Path to the .gguf model file",
    )
    parser.add_argument(
        "--ctx", "-c",
        type=int,
        default=4096,
        help="Context window size (default: 4096)",
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=None,
        help="CPU threads to use (default: auto)",
    )
    parser.add_argument(
        "--gpu-layers", "-g",
        type=int,
        default=0,
        help="GPU layers to offload (0 = CPU only, -1 = all)",
    )
    parser.add_argument(
        "--workspace", "-w",
        default="./workspace",
        help="Working directory for generated files (default: ./workspace)",
    )
    parser.add_argument(
        "--temp",
        type=float,
        default=0.2,
        help="Temperature for generation (default: 0.2)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose llama.cpp output",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    settings = Settings(
        model_path=args.model,
        context_size=args.ctx,
        threads=args.threads,
        gpu_layers=args.gpu_layers,
        workspace=args.workspace,
        temperature=args.temp,
        verbose=args.verbose,
    )

    repl = CodeAgentREPL(settings)
    try:
        repl.run()
    except KeyboardInterrupt:
        print("\n\n👋 Bye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
