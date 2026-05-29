```python

"""
GGUF Code Agent
Terminal-based VS Code-style coding agent powered by local GGUF models.

Examples:
    python main.py

    python main.py \
        --model /path/to/model.gguf

    python main.py \
        --model workspace/models/Qwen3.5-2B-UD-Q8_K_XL.gguf \
        --workspace ./workspace \
        --ctx 8192 \
        --gpu-layers -1
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.request import urlretrieve

from agent.repl import CodeAgentREPL
from config.settings import Settings


DEFAULT_WORKSPACE = Path("./workspace")
DEFAULT_MODEL_DIR = DEFAULT_WORKSPACE / "models"

DEFAULT_MODEL_NAME = "Qwen3.5-2B-UD-Q4_K_XL.gguf"

DEFAULT_MODEL_URL = (
    "https://huggingface.co/unsloth/"
    "Qwen3.5-2B-MTP-GGUF/resolve/main/"
    "Qwen3.5-2B-UD-Q4_K_XL.gguf?download=true"
)


def ensure_model_exists(model_path: Path):
    """
    Automatically download the default GGUF model
    if it does not exist locally.
    """

    if model_path.exists():
        return

    model_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n📥 Model not found:")
    print(f"   {model_path}")
    print("\n⬇ Downloading default GGUF model...")
    print("   This may take several minutes.\n")

    try:
        urlretrieve(DEFAULT_MODEL_URL, model_path)

        print("\n✅ Model download complete")
        print(f"📁 Saved to: {model_path}\n")

    except Exception as exc:
        print(f"\n❌ Failed to download model:\n{exc}")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GGUF Code Agent - Local terminal coding assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Examples:

  python main.py

  python main.py \
      --model /path/to/model.gguf

  python main.py \
      --model workspace/models/Qwen3.5-2B-UD-Q8_K_XL.gguf \
      --ctx 8192 \
      --threads 8

  python main.py \
      --workspace ./workspace
        """,
    )

    parser.add_argument(
        "--model",
        "-m",
        default=str(DEFAULT_MODEL_DIR / DEFAULT_MODEL_NAME),
        help=(
            "Path to GGUF model file "
            f"(default: {DEFAULT_MODEL_DIR / DEFAULT_MODEL_NAME})"
        ),
    )

    parser.add_argument(
        "--ctx",
        "-c",
        type=int,
        default=4096,
        help="Context window size (default: 4096)",
    )

    parser.add_argument(
        "--threads",
        "-t",
        type=int,
        default=None,
        help="CPU threads to use (default: auto)",
    )

    parser.add_argument(
        "--gpu-layers",
        "-g",
        type=int,
        default=0,
        help="GPU layers to offload (-1 = full GPU offload)",
    )

    parser.add_argument(
        "--workspace",
        "-w",
        default=str(DEFAULT_WORKSPACE),
        help="Workspace directory (default: ./workspace)",
    )

    parser.add_argument(
        "--temp",
        type=float,
        default=0.2,
        help="Sampling temperature (default: 0.2)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose llama.cpp logging",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    workspace_path = Path(args.workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)

    model_path = Path(args.model)

    ensure_model_exists(model_path)

    settings = Settings(
        model_path=str(model_path),
        context_size=args.ctx,
        threads=args.threads,
        gpu_layers=args.gpu_layers,
        workspace=str(workspace_path),
        temperature=args.temp,
        verbose=args.verbose,
    )

    repl = CodeAgentREPL(settings)

    try:
        repl.run()

    except KeyboardInterrupt:
        print("\n\n👋 Session terminated")
        sys.exit(0)


if __name__ == "__main__":
    main()
```
