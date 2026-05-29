# GGUF Code Agent

A professional terminal-based AI coding assistant powered entirely by local GGUF language models through `llama.cpp`.

The project delivers a lightweight, VS Code-inspired development workflow directly inside the terminal while maintaining complete offline capability after the initial model download.

The agent supports modern GGUF instruction-tuned models including Qwen, DeepSeek, Mistral, Phi, CodeLlama, and Llama-family variants. It provides real-time streaming inference, persistent conversational memory, workspace-aware code generation, syntax-highlighted rendering, and integrated code execution utilities.

---

# Features

| Capability | Description |
|---|---|
| Local LLM Inference | Fully offline inference using `llama-cpp-python` |
| GGUF Compatibility | Supports most ChatML-compatible GGUF models |
| Real-Time Streaming | Incremental token streaming during generation |
| Workspace Awareness | Automatically exposes project structure and files to the model |
| Multi-Turn Memory | Persistent conversational context across prompts |
| Syntax Highlighting | Rich terminal rendering with formatted code blocks |
| File Operations | Save generated code directly into the workspace |
| Code Execution | Execute generated Python, Bash, JavaScript, Go, Ruby, and other scripts |
| Multi-Line Prompt Mode | Paste large prompts or code blocks interactively |
| VS Code Integration | Open the active workspace directly in VS Code |
| GPU Acceleration | CUDA and Metal GPU offloading support |
| Portable Architecture | Works across Linux, macOS, and Windows |

---

# General Workspace Layout

The application uses a generalized workspace structure without hardcoded project-specific paths.

```text
workspace/
├── models/              # GGUF model storage
├── projects/            # Generated project files
├── sessions/            # Conversation/session history
├── outputs/             # Generated outputs and exports
└── cache/               # Temporary runtime cache
````

All runtime-generated files are automatically organized inside the workspace directory.

---

# Installation

## Clone the Repository

```bash
git clone <repository-url>
cd gguf-code-agent
```

## Install Dependencies

```bash
bash install.sh
```

Or manually:

```bash
pip install -r requirements.txt
```

---

# Automatic Model Download

If the specified model file does not exist locally, the application automatically downloads a supported Qwen GGUF model from Hugging Face.

Repository:

https://huggingface.co/unsloth/Qwen3.5-2B-MTP-GGUF

Supported Downloads:

```text
Q8 Model:
https://huggingface.co/unsloth/Qwen3.5-2B-MTP-GGUF/resolve/main/Qwen3.5-2B-UD-Q8_K_XL.gguf?download=true

Q4 Model:
https://huggingface.co/unsloth/Qwen3.5-2B-MTP-GGUF/resolve/main/Qwen3.5-2B-UD-Q4_K_XL.gguf?download=true
```

Models are stored automatically inside:

```text
workspace/models/
```

---

# Quick Start

## Launch with Automatic Model Handling

```bash
python main.py
```

If no model exists inside `workspace/models/`, the application automatically downloads a default GGUF model.

---

## Launch with a Specific Model

```bash
python main.py \
    --model workspace/models/Qwen3.5-2B-UD-Q8_K_XL.gguf
```

---

## Example with GPU Acceleration

```bash
python main.py \
    --model workspace/models/Qwen3.5-2B-UD-Q8_K_XL.gguf \
    --gpu-layers -1 \
    --ctx 8192 \
    --threads 8
```

---

# Command Line Interface

```text
python main.py [options]
```

| Option               | Description                   |
| -------------------- | ----------------------------- |
| `--model`, `-m`      | Path to GGUF model            |
| `--workspace`, `-w`  | Base workspace directory      |
| `--ctx`, `-c`        | Context window size           |
| `--threads`, `-t`    | CPU thread count              |
| `--gpu-layers`, `-g` | GPU layers to offload         |
| `--temp`             | Sampling temperature          |
| `--verbose`, `-v`    | Enable verbose llama.cpp logs |

---

# Interactive Commands

| Command        | Description                      |
| -------------- | -------------------------------- |
| `/help`        | Show available commands          |
| `/save [name]` | Save latest generated code block |
| `/run`         | Execute latest generated code    |
| `/show`        | Re-display last model response   |
| `/history`     | Display conversation history     |
| `/clear`       | Reset active conversation        |
| `/multi`       | Multi-line input mode            |
| `/tree`        | Show workspace directory tree    |
| `/open <path>` | Load a file into model context   |
| `/workspace`   | Open workspace in VS Code        |
| `/exit`        | Exit the application             |

---

# Workspace-Aware Development

The agent automatically provides the model with awareness of:

* Project structure
* Opened files
* Previously generated outputs
* Workspace file tree
* Current session history

Example prompts:

```text
Read main.py and explain the architecture
Refactor utils/parser.py
Generate tests for api/client.py
Summarize the README
```

---

# Supported Models

The application supports most modern GGUF instruction models.

Recommended models include:

* Qwen3.5
* DeepSeek Coder
* Mistral
* Mixtral
* Phi-3 / Phi-4
* CodeLlama
* Llama 3.x

ChatML-compatible models work without additional prompt customization.

For non-ChatML models, modify prompt formatting inside:

```text
agent/llm_engine.py
```

---

# GPU Support

## NVIDIA CUDA

```bash
CMAKE_ARGS="-DGGML_CUDA=on" \
pip install llama-cpp-python --upgrade
```

## Apple Silicon Metal

```bash
CMAKE_ARGS="-DGGML_METAL=on" \
pip install llama-cpp-python --upgrade
```

---

# Project Structure

```text
gguf-code-agent/
├── main.py
├── requirements.txt
├── install.sh
├── agent/
│   ├── llm_engine.py
│   └── repl.py
├── tools/
│   ├── code_tools.py
│   └── ui.py
├── config/
│   └── settings.py
└── workspace/
    ├── models/
    ├── projects/
    ├── sessions/
    ├── outputs/
    └── cache/
```

---

# Example Session

```text
❯ write a Python function that merges two sorted arrays

def merge_sorted(a, b):
    result = []
    i = j = 0

    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1

    result.extend(a[i:])
    result.extend(b[j:])

    return result

ℹ 1 code block detected

❯ /run

✔ Saved → workspace/projects/output_001.py

▶ Execution complete
```

---

# Design Goals

The architecture is designed around the following engineering principles:

* Fully local execution
* Minimal external dependencies
* Cross-platform portability
* Fast startup and inference
* Workspace-centric development
* Terminal-native interaction
* Extensible tooling architecture


