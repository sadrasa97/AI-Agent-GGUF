# 🤖 GGUF Code Agent

A **terminal-based VS Code-style coding agent** that runs fully locally using any GGUF model (Qwen, DeepSeek, Mistral, CodeLlama, Phi, etc.).  
No internet required after model download.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🧠 Local inference | Pure llama.cpp via `llama-cpp-python` |
| 💬 Streaming output | Tokens print in real-time as they generate |
| 🎨 Syntax highlighting | `rich`-powered code blocks with line numbers |
| 💾 Save to disk | `/save [filename]` writes code to workspace |
| ▶️  Run code | `/run` executes Python, JS, Bash, Go, Ruby… |
| 🗂 Multi-turn history | Full conversation context across turns |
| 📁 Workspace context | Model sees workspace tree and opened files |
| 🧠 Natural file access | Ask for `main.py` or `README.md` directly in chat |
| 📝 Multi-line input | `/multi` for pasting long prompts |
| 🖥 VS Code integration | `/workspace` opens folder in VS Code |
| ⚡ GPU support | `--gpu-layers N` for CUDA/Metal offload |

---

## 🚀 Quick Start

```bash
# 1. Clone / copy this folder
cd gguf-code-agent

# 2. Install
bash install.sh

# 3. Download a model  (example with huggingface-hub)
pip install huggingface-hub
huggingface-cli download bartowski/Qwen3.5-2B-GGUF \
    Qwen3.5-2B-UD-Q8_K_XL.gguf --local-dir ./models

# 4. Run!
python main.py --model D:\models\Qwen3.5-2B-Q4_K_S.gguf
```

---

## 🎛 CLI Options

```
python main.py [options]

  --model  / -m   PATH     Path to .gguf model file         (required)
  --ctx    / -c   INT      Context window size               (default: 4096)
  --threads/ -t   INT      CPU threads                       (default: auto)
  --gpu-layers/-g INT      GPU layers to offload; -1 = all  (default: 0)
  --workspace/-w  PATH     Output folder for saved files     (default: ./workspace)
  --temp          FLOAT    Temperature                       (default: 0.2)
  --verbose / -v           Show llama.cpp internals
```

### Example with GPU
```bash
python main.py --model ./models/Qwen3.5-2B-UD-Q8_K_XL.gguf \
               --gpu-layers -1 --ctx 8192 --threads 4
```

---

## 💬 REPL Commands

| Command | Description |
|---|---|
| `/help` | Show command list |
| `/save [name]` | Save last code block → workspace |
| `/run` | Save + execute last code block |
| `/show` | Re-display last full response |
| `/history` | Print conversation turns |
| `/clear` | Reset conversation |
| `/multi` | Multi-line prompt (end with `;;`) |
| `/tree` | Show workspace file tree |
| `/open <path>` | Open a workspace file and add it to context |
| `/workspace` | Open workspace in VS Code |
| `/exit` | Quit |

You can also ask in plain language, for example:

- `main.py رو بخون و توضیح بده`
- `README.md رو بخون و خلاصه کن`
- `agent/repl.py رو بررسی کن`

---

## 📂 Project Structure

```
gguf-code-agent/
├── main.py              # Entry point & CLI argument parsing
├── requirements.txt
├── install.sh
├── agent/
│   ├── llm_engine.py    # llama-cpp-python wrapper + ChatML prompt builder
│   └── repl.py          # Main REPL loop + command dispatcher
├── tools/
│   ├── code_tools.py    # Code block extraction, save, run
│   └── ui.py            # Rich / ANSI terminal UI helpers
├── config/
│   └── settings.py      # Settings dataclass
└── workspace/           # Generated files land here (auto-created)
```

---

## 🔌 Supported GGUF Models

Any ChatML-compatible model works out of the box:

- **Qwen3.5-2B / 7B** (recommended — excellent at code)
- DeepSeek Coder v2
- Mistral 7B / Mixtral
- CodeLlama 7B–34B
- Phi-3 / Phi-4
- Llama 3.1 / 3.2

For non-ChatML models (e.g. Llama-2 style), adjust `_build_prompt()` in `agent/llm_engine.py`.

---

## 🛠 GPU Install

**NVIDIA CUDA:**
```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --upgrade
```

**Apple Silicon (Metal):**
```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --upgrade
```

---

## 📝 Example Session

```
❯ #1  write a python function that merges two sorted lists

def merge_sorted(a, b):
    result, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i]); i += 1
        else:
            result.append(b[j]); j += 1
    return result + a[i:] + b[j:]

ℹ  1 code block found — use /save or /run

❯ #2  /run
✔  Saved → workspace/output_001.py
▶ Output:
(no output — pure function, no print call)

❯ #3  add a test and print the result

...
```
