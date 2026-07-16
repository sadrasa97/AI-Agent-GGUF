"""Targeted patch for qwen_asr qwen3_asr.py compatibility issues.

This script intentionally applies a narrow, idempotent replacement and avoids
generic indentation edits that can corrupt nested try/except blocks.
"""

from pathlib import Path


PATH = Path(
    r"C:\Users\sadra\AppData\Local\Programs\Python\Python312\Lib\site-packages\qwen_asr\inference\qwen3_asr.py"
)


BROKEN_BLOCK = """try:
    from qwen_asr.core.vllm_backend import Qwen3ASRForConditionalGeneration
    from vllm import ModelRegistry
    try:
    ModelRegistry.register_model(\"Qwen3ASRForConditionalGeneration\", Qwen3ASRForConditionalGeneration)
except (ValueError, Exception):
    pass
except:
    pass
"""

FIXED_BLOCK = """try:
    from qwen_asr.core.vllm_backend import Qwen3ASRForConditionalGeneration
    from vllm import ModelRegistry
    try:
        ModelRegistry.register_model(\"Qwen3ASRForConditionalGeneration\", Qwen3ASRForConditionalGeneration)
    except (ValueError, Exception):
        pass
except Exception:
    pass
"""


def main() -> None:
    if not PATH.is_file():
        raise FileNotFoundError(f"qwen3_asr.py not found: {PATH}")

    text = PATH.read_text(encoding="utf-8")
    if BROKEN_BLOCK in text:
        PATH.write_text(text.replace(BROKEN_BLOCK, FIXED_BLOCK), encoding="utf-8")
        print("Applied targeted qwen3_asr block fix.")
    else:
        print("No broken block found; no changes made.")


if __name__ == "__main__":
    main()
