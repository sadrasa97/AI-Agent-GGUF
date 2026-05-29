#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# GGUF Code Agent — installer
# ─────────────────────────────────────────────────────────────────────
set -e

echo "🔧 Installing GGUF Code Agent dependencies…"

# ── 1. plain CPU build (default) ────────────────────────────────────
pip install -r requirements.txt -i https://mirror-pypi.runflare.com/simple

echo ""
echo "✅ Done!  (CPU build)"
echo ""
echo "───────────────────────────────────────────────────────────────"
echo "  If you have an NVIDIA GPU, run instead:"
echo "  CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python --upgrade"
echo ""
echo "  If you have an Apple Silicon Mac (Metal):"
echo "  CMAKE_ARGS=\"-DGGML_METAL=on\" pip install llama-cpp-python --upgrade"
echo "───────────────────────────────────────────────────────────────"
echo ""
echo "  Usage:"
echo "  python main.py --model /path/to/Qwen3.5-2B-UD-Q8_K_XL.gguf"
echo ""
