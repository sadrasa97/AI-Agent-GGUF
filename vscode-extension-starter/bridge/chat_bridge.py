from __future__ import annotations

import json
import sys
from pathlib import Path


def _resolve_repo_root() -> Path:
    # bridge/chat_bridge.py -> vscode-extension-starter -> repo root
    return Path(__file__).resolve().parents[2]


def _load_runtime(payload: dict) -> str:
    repo_root = _resolve_repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from config.settings import Settings
    from agent.providers import create_provider, ProviderError

    settings = Settings.load()
    backend = str(payload.get("backend", settings.backend)).strip() or settings.backend
    settings.backend = backend
    settings.workspace = str(repo_root)

    if settings.backend == "gguf" and not settings.model_path:
        model_dir = repo_root / "workspace" / "models"
        if model_dir.exists() and model_dir.is_dir():
            models = sorted(model_dir.glob("*.gguf"))
            if models:
                settings.model_path = str(models[0].resolve())

    prompt = str(payload.get("prompt", "")).strip()
    mode = str(payload.get("mode", "Chat")).strip()

    if mode.lower() == "plan":
        prompt = (
            "You are in PLAN mode. Provide a concise step-by-step plan before code.\n\n"
            + prompt
        )

    history = [{"role": "user", "content": prompt}]

    provider = None
    try:
        provider = create_provider(settings)
        text = "".join(provider.stream(history, workspace_context=None))
        return text.strip() or "(empty response)"
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if provider is not None:
            provider.close()


def main() -> int:
    try:
        if len(sys.argv) < 2:
            raise RuntimeError("Missing bridge payload argument.")

        payload = json.loads(sys.argv[1])
        answer = _load_runtime(payload)
        print(json.dumps({"ok": True, "text": answer}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
