from __future__ import annotations

from pathlib import Path

import requests

from config.settings import Settings


def default_gguf_target_path(settings: Settings) -> Path:
    """Return where the default GGUF model should live for this workspace."""
    workspace = settings.workspace_path
    return workspace / "workspace" / "models" / settings.default_gguf_filename


def ensure_default_gguf_model(
    settings: Settings,
    force_download: bool = False,
    timeout_seconds: int = 600,
) -> tuple[Path, bool]:
    """
    Ensure a default GGUF model exists and update settings.model_path.

    Returns (path, downloaded_now).
    """
    configured_path = Path(settings.model_path).expanduser() if settings.model_path else None
    if configured_path and configured_path.exists() and configured_path.is_file() and not force_download:
        settings.model_path = str(configured_path.resolve())
        return configured_path.resolve(), False

    target = default_gguf_target_path(settings).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.is_file() and not force_download:
        settings.model_path = str(target)
        return target, False

    url = settings.default_gguf_url.strip()
    if not url:
        raise RuntimeError("Default GGUF URL is empty.")

    tmp_path = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout_seconds) as response:
            response.raise_for_status()
            with tmp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
        tmp_path.replace(target)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    settings.model_path = str(target)
    return target, True
