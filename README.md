# Nova Code Agent

A professional terminal-based AI coding assistant powered entirely by local GGUF language models through `llama.cpp`.

The project delivers a lightweight, VS Code-inspired development workflow directly inside the terminal while maintaining complete offline capability after the initial model download.

The agent supports modern GGUF instruction-tuned models including Qwen, DeepSeek, Mistral, Phi, CodeLlama, and Llama-family variants. It provides real-time streaming inference, persistent conversational memory, workspace-aware code generation, syntax-highlighted rendering, and integrated code execution utilities.

---

# Features

| Capability | Description |
|------------|-------------|
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

# Installation

## Clone the Repository

