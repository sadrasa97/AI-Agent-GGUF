"""Voice input utilities (record + transcribe) for the chat UI."""
from __future__ import annotations

import os
import tempfile
import time
import wave
import json
from pathlib import Path
from typing import Callable, Optional

import requests

from config.settings import Settings


class VoiceError(RuntimeError):
    pass


# Cached ASR pipeline to avoid reloading the model on every transcription
_cached_asr_pipeline: Optional[object] = None
_cached_asr_model_id: Optional[str] = None


def record_microphone_wav(seconds: float = 6.0, sample_rate: int = 16000) -> Path:
    """Record a short mono WAV file from the default microphone.

    Returns a temporary file path. Caller is responsible for deleting it.
    """
    if seconds <= 0:
        raise VoiceError("Recording duration must be > 0 seconds.")

    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(
            "Microphone recording requires sounddevice. Install with: pip install sounddevice"
        ) from exc

    try:
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise VoiceError("Microphone recording requires numpy. Install with: pip install numpy") from exc

    frames = int(seconds * sample_rate)
    try:
        audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"Microphone recording failed: {exc}") from exc

    # Convert float32 [-1,1] to int16 PCM
    pcm = (audio.flatten().clip(-1.0, 1.0) * 32767.0).astype(np.int16)

    handle, temp_name = tempfile.mkstemp(prefix="gguf_agent_voice_", suffix=".wav")
    os.close(handle)
    out = Path(temp_name)

    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

    return out


def record_microphone_wav_until_stop(sample_rate: int, should_stop: Callable[[], bool]) -> Path:
    """Record mono WAV from microphone until should_stop() returns True."""
    if sample_rate <= 0:
        raise VoiceError("Sample rate must be > 0")

    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(
            "Microphone recording requires sounddevice. Install with: pip install sounddevice"
        ) from exc

    try:
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise VoiceError("Microphone recording requires numpy. Install with: pip install numpy") from exc

    chunks: list[np.ndarray] = []

    def _callback(indata, frames, _time, _status):
        del frames
        chunks.append(indata.copy())

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=_callback):
            while not should_stop():
                time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"Microphone recording failed: {exc}") from exc

    if not chunks:
        raise VoiceError("No audio was captured from microphone.")

    audio = np.concatenate(chunks, axis=0)
    pcm = (audio.flatten().clip(-1.0, 1.0) * 32767.0).astype(np.int16)

    handle, temp_name = tempfile.mkstemp(prefix="gguf_agent_voice_", suffix=".wav")
    os.close(handle)
    out = Path(temp_name)

    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

    return out


def transcribe_audio_file(audio_path: Path, settings: Settings) -> str:
    backend = (settings.asr_backend or "local").strip().lower()
    if backend == "local":
        return _transcribe_local(audio_path, settings)
    if backend == "api":
        return _transcribe_api(audio_path, settings)
    raise VoiceError(f"Unknown ASR backend: {settings.asr_backend}")


_WHISPER_FALLBACK = "openai/whisper-base"

# Cached Qwen3 ASR model instance
_cached_qwen3_asr_model: Optional[object] = None
_cached_qwen3_asr_path: Optional[str] = None


def _ensure_qwen_factor_config(model_path: str) -> None:
    """Patch qwen config for older loaders that expect rope_scaling.factor.

    Some qwen_asr/transformers combinations raise KeyError('factor') when
    rope_scaling exists but misses a numeric factor.
    """
    if not os.path.isdir(model_path):
        return
    config_path = os.path.join(model_path, "config.json")
    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        return

    changed = False

    def _patch_rope_scaling(obj: dict) -> bool:
        if not isinstance(obj, dict):
            return False
        rope = obj.get("rope_scaling")
        if not isinstance(rope, dict):
            return False
        if "factor" in rope:
            return False
        rope["factor"] = 1.0
        return True

    # thinker_config.text_config.rope_scaling is where this model stores qwen3 text params.
    thinker_cfg = cfg.get("thinker_config")
    if isinstance(thinker_cfg, dict):
        text_cfg = thinker_cfg.get("text_config")
        if isinstance(text_cfg, dict) and _patch_rope_scaling(text_cfg):
            changed = True

    # Also patch top-level rope_scaling if present.
    if _patch_rope_scaling(cfg):
        changed = True

    if not changed:
        return

    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:
        return


def _patch_check_model_inputs():
    """Patch transformers check_model_inputs to work as both @decorator and @decorator().
    Also patch AutoConfig.register to allow re-registration of existing model types."""
    try:
        import transformers.utils.generic as _generic
        _orig = getattr(_generic, "check_model_inputs", None)
        if _orig is None:
            return
        import inspect
        sig = inspect.signature(_orig)
        params = list(sig.parameters.keys())
        # If it only accepts (func), wrap it so () also works
        if len(params) == 1 and params[0] == "func":
            import functools

            @functools.wraps(_orig)
            def _compat(*args, **kwargs):
                if args and callable(args[0]):
                    return _orig(args[0])
                # Called as @check_model_inputs() — return the original as decorator
                return _orig

            _generic.check_model_inputs = _compat
    except Exception:
        pass

    # Patch CONFIG_MAPPING.register and model mappings to FORCE re-registration
    # (qwen_asr's custom classes must override transformers' built-in ones)
    try:
        from transformers.models.auto import configuration_auto, auto_factory

        # Patch CONFIG_MAPPING.register to force overwrite
        _orig_cm_register = configuration_auto.CONFIG_MAPPING.register

        def _force_cm_register(key, value, exist_ok=False):
            # Remove existing entry first, then register
            try:
                if key in configuration_auto.CONFIG_MAPPING._mapping:
                    del configuration_auto.CONFIG_MAPPING._mapping[key]
            except Exception:
                pass
            try:
                _orig_cm_register(key, value, exist_ok=True)
            except TypeError:
                try:
                    _orig_cm_register(key, value)
                except ValueError:
                    pass
            except ValueError:
                pass

        configuration_auto.CONFIG_MAPPING.register = _force_cm_register

        # Patch _LazyAutoMapping.register to force overwrite
        _orig_lazy_register = auto_factory._LazyAutoMapping.register

        def _force_lazy_register(self, key, value, exist_ok=False):
            # Remove existing entry
            try:
                if key in self._mapping:
                    del self._mapping[key]
            except Exception:
                pass
            try:
                if hasattr(self, '_extra_content') and key in self._extra_content:
                    del self._extra_content[key]
            except Exception:
                pass
            try:
                _orig_lazy_register(self, key, value, exist_ok=True)
            except TypeError:
                try:
                    _orig_lazy_register(self, key, value)
                except ValueError:
                    pass
            except ValueError:
                pass

        auto_factory._LazyAutoMapping.register = _force_lazy_register
    except Exception:
        pass


def _load_qwen3_asr(model_path: str):
    """Load Qwen3ASRModel using the qwen_asr package."""
    global _cached_qwen3_asr_model, _cached_qwen3_asr_path

    if _cached_qwen3_asr_model is not None and _cached_qwen3_asr_path == model_path:
        return _cached_qwen3_asr_model

    _ensure_qwen_factor_config(model_path)
    _patch_check_model_inputs()

    # Patch Qwen3ASRConfig.get_text_config to handle uninitialized state
    # (transformers 5.14 dev validates during __init__ before thinker_config is set)
    try:
        from qwen_asr.core.transformers_backend.configuration_qwen3_asr import Qwen3ASRConfig
        _orig_get_text_config = Qwen3ASRConfig.get_text_config

        def _safe_get_text_config(self, *args, **kwargs):
            if not hasattr(self, 'thinker_config') or self.thinker_config is None:
                # Return self as fallback during init (before thinker_config is set)
                return self
            return _orig_get_text_config(self, *args, **kwargs)

        Qwen3ASRConfig.get_text_config = _safe_get_text_config
    except Exception:
        pass

    # Patch thinker config with token-id defaults required by some transformers paths.
    try:
        from qwen_asr.core.transformers_backend.configuration_qwen3_asr import Qwen3ASRThinkerConfig

        _missing_defaults = {
            "pad_token_id": None,
            "bos_token_id": None,
            "eos_token_id": None,
            "sep_token_id": None,
            "decoder_start_token_id": None,
        }
        for _name, _value in _missing_defaults.items():
            if not hasattr(Qwen3ASRThinkerConfig, _name):
                setattr(Qwen3ASRThinkerConfig, _name, _value)

        _orig_thinker_init = getattr(Qwen3ASRThinkerConfig, "__init__", None)

        def _patched_thinker_init(self, *args, **kwargs):
            if _orig_thinker_init is not None:
                _orig_thinker_init(self, *args, **kwargs)
            for _name, _value in _missing_defaults.items():
                if not hasattr(self, _name):
                    setattr(self, _name, _value)

        Qwen3ASRThinkerConfig.__init__ = _patched_thinker_init
    except Exception:
        pass

    try:
        import torch
        from qwen_asr import Qwen3ASRModel
    except ImportError as exc:
        raise VoiceError(
            "qwen_asr package is required for Qwen3-ASR. "
            "Install with: pip install qwen-asr"
        ) from exc

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

    # Patch missing rotary helper method for newer transformers compatibility.
    try:
        import qwen_asr.core.transformers_backend.modeling_qwen3_asr as _qwen_asr_modeling
        from transformers.models.qwen3.modeling_qwen3 import Qwen3RotaryEmbedding as _HFQwen3RotaryEmbedding

        _asr_rotary = getattr(_qwen_asr_modeling, "Qwen3ASRThinkerTextRotaryEmbedding", None)
        _hf_method = getattr(_HFQwen3RotaryEmbedding, "compute_default_rope_parameters", None)
        if _asr_rotary is not None and _hf_method is not None and not hasattr(_asr_rotary, "compute_default_rope_parameters"):
            setattr(_asr_rotary, "compute_default_rope_parameters", _hf_method)

        if _asr_rotary is not None:
            _orig_rotary_init = getattr(_asr_rotary, "__init__", None)

            def _patched_rotary_init(self, *args, **kwargs):
                if _orig_rotary_init is not None:
                    _orig_rotary_init(self, *args, **kwargs)

                cfg = getattr(self, "config", None)
                rope_scaling = getattr(cfg, "rope_scaling", None)
                rope_params = rope_scaling if isinstance(rope_scaling, dict) else {"rope_type": "default"}
                if "rope_type" not in rope_params:
                    rope_params["rope_type"] = rope_params.get("type", "default")
                if "factor" not in rope_params:
                    rope_params["factor"] = 1.0

                self.rope_parameters = rope_params
                if not hasattr(self, "max_position_embeddings") and cfg is not None:
                    self.max_position_embeddings = getattr(cfg, "max_position_embeddings", 4096)

            _asr_rotary.__init__ = _patched_rotary_init

            # Some qwen_asr builds decorate forward with dynamic_rope_update
            # that expects newer RotaryEmbedding attributes not present here.
            # Falling back to the undecorated forward keeps inference working.
            _forward = getattr(_asr_rotary, "forward", None)
            _raw_forward = getattr(_forward, "__wrapped__", None)
            if _raw_forward is not None:
                _asr_rotary.forward = _raw_forward
    except Exception:
        pass

    attempts = [
        {"dtype": dtype, "device_map": device, "max_new_tokens": 256, "trust_remote_code": True},
        {"dtype": dtype, "device_map": device, "trust_remote_code": True},
        {"torch_dtype": dtype, "device_map": device, "trust_remote_code": True},
        {"dtype": dtype, "max_new_tokens": 256, "trust_remote_code": True},
        {"dtype": dtype, "trust_remote_code": True},
        {"trust_remote_code": True},
        {},
    ]
    errors: list[str] = []
    model = None

    for kwargs in attempts:
        try:
            model = Qwen3ASRModel.from_pretrained(model_path, **kwargs)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"kwargs={kwargs}: {exc}")

    if model is None:
        short_errors = " | ".join(errors[-3:])
        raise VoiceError(
            f"Failed to load Qwen3-ASR model from '{model_path}': {short_errors}"
        )

    _cached_qwen3_asr_model = model
    _cached_qwen3_asr_path = model_path
    return model


def _is_qwen3_asr_model(model_id: str) -> bool:
    """Check if model_id points to a Qwen3-ASR checkpoint."""
    config_path = os.path.join(model_id, "config.json") if os.path.isdir(model_id) else None
    if config_path and os.path.isfile(config_path):
        import json
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            return cfg.get("model_type") == "qwen3_asr"
        except Exception:
            pass
    return False


def _transcribe_local(audio_path: Path, settings: Settings) -> str:
    model_id = (settings.qwen_voice_model_path or settings.asr_model_path or "").strip()
    if not model_id:
        raise VoiceError("Local ASR model path/id is empty. Set it in Settings.")

    # --- Qwen3-ASR path: use qwen_asr package directly ---
    if _is_qwen3_asr_model(model_id):
        return _transcribe_qwen3_asr(audio_path, model_id, settings)

    # --- Generic HuggingFace ASR pipeline (whisper, wav2vec, etc.) ---
    return _transcribe_hf_pipeline(audio_path, model_id, settings)


_QWEN3_ASR_TARGET_SR = 16000


def _load_audio_as_float32_mono(audio_path: Path) -> tuple:
    """Load an audio file into a float32 mono numpy array + sample rate.

    Tries soundfile first (fast path for real WAV/FLAC/OGG-Vorbis files).
    Falls back to pydub/ffmpeg for anything soundfile can't parse -- this
    covers audio coming from a browser's MediaRecorder, which is usually
    webm/opus (or ogg/opus) even if it was uploaded with a ".wav" name/label.
    """
    import numpy as np

    try:
        import soundfile as sf
        audio_np, sr = sf.read(str(audio_path), dtype="float32")
        if getattr(audio_np, "ndim", 1) > 1:
            audio_np = audio_np.mean(axis=1)
        return audio_np, sr
    except Exception:
        pass

    try:
        from pydub import AudioSegment
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(
            "Could not decode the recorded audio. It doesn't look like a "
            "plain WAV file (e.g. it may be webm/opus from a browser "
            "recorder). Install pydub + ffmpeg to support this format: "
            "pip install pydub (and ensure ffmpeg is on PATH)."
        ) from exc

    try:
        seg = AudioSegment.from_file(str(audio_path))
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"Failed to decode audio file '{audio_path}': {exc}") from exc

    seg = seg.set_channels(1)
    sr = seg.frame_rate
    samples = np.array(seg.get_array_of_samples())

    if seg.sample_width == 2:
        audio_np = samples.astype(np.float32) / 32768.0
    elif seg.sample_width == 4:
        audio_np = samples.astype(np.float32) / 2147483648.0
    else:
        # sample_width == 1 (unsigned 8-bit) or anything unusual
        audio_np = (samples.astype(np.float32) - 128.0) / 128.0

    return audio_np, sr


def _resample_to_16k(audio_np, sr: int):
    """Resample audio to 16kHz mono if needed. Qwen3-ASR expects 16kHz."""
    if sr == _QWEN3_ASR_TARGET_SR:
        return audio_np, sr

    try:
        import librosa
        audio_np = librosa.resample(audio_np, orig_sr=sr, target_sr=_QWEN3_ASR_TARGET_SR)
        return audio_np, _QWEN3_ASR_TARGET_SR
    except Exception:
        pass

    # Fallback: simple resampling via scipy if librosa isn't available.
    try:
        from scipy.signal import resample
        n_samples = int(len(audio_np) * _QWEN3_ASR_TARGET_SR / sr)
        audio_np = resample(audio_np, n_samples).astype("float32")
        return audio_np, _QWEN3_ASR_TARGET_SR
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(
            f"Audio is sampled at {sr}Hz but Qwen3-ASR expects "
            f"{_QWEN3_ASR_TARGET_SR}Hz, and resampling failed: {exc}. "
            "Install librosa or scipy: pip install librosa"
        ) from exc


def _transcribe_qwen3_asr(audio_path: Path, model_path: str, settings: Settings) -> str:
    """Transcribe using qwen_asr.Qwen3ASRModel."""
    model = _load_qwen3_asr(model_path)

    audio_np, sr = _load_audio_as_float32_mono(audio_path)
    audio_np, sr = _resample_to_16k(audio_np, sr)

    language = (settings.asr_language or "").strip()
    lang = None if not language or language.lower() == "auto" else language

    try:
        results = model.transcribe(audio=(audio_np, sr), language=lang)
    except Exception as exc:
        raise VoiceError(f"Qwen3-ASR transcription failed: {exc}") from exc

    if not results:
        raise VoiceError("Qwen3-ASR returned no results.")

    text = getattr(results[0], "text", "").strip()
    if not text:
        raise VoiceError("Qwen3-ASR returned empty text.")
    return text


def _transcribe_hf_pipeline(audio_path: Path, model_id: str, settings: Settings) -> str:
    """Transcribe using a standard HuggingFace ASR pipeline."""
    global _cached_asr_pipeline, _cached_asr_model_id

    try:
        from transformers import pipeline as hf_pipeline
    except Exception as exc:
        raise VoiceError(
            "Local ASR requires transformers and torch. Install with: pip install transformers torch"
        ) from exc

    if _cached_asr_pipeline is not None and _cached_asr_model_id == model_id:
        pipe = _cached_asr_pipeline
    else:
        try:
            pipe = hf_pipeline("automatic-speech-recognition", model=model_id)
        except Exception as exc:
            raise VoiceError(f"Failed to load ASR model '{model_id}': {exc}") from exc
        _cached_asr_pipeline = pipe
        _cached_asr_model_id = model_id

    # Read WAV as numpy array to avoid ffmpeg dependency
    import numpy as np
    with wave.open(str(audio_path), "rb") as wf:
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        sample_width = wf.getsampwidth()
        sr = wf.getframerate()

    if sample_width == 2:
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio_np = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    audio_input = {"raw": audio_np, "sampling_rate": sr}

    kwargs = {}
    language = (settings.asr_language or "").strip()
    if language and language.lower() != "auto":
        kwargs["generate_kwargs"] = {"language": language}

    try:
        result = pipe(audio_input, **kwargs)
    except TypeError:
        result = pipe(audio_input)
    except ValueError as exc:
        if "model_kwargs" in str(exc):
            result = pipe(audio_input)
        else:
            raise VoiceError(f"Local transcription failed: {exc}") from exc
    except Exception as exc:
        raise VoiceError(f"Local transcription failed: {exc}") from exc

    if isinstance(result, dict):
        text = (result.get("text") or "").strip()
    else:
        text = str(result).strip()
    if not text:
        raise VoiceError("Local ASR returned empty text.")
    return text


def _transcribe_api(audio_path: Path, settings: Settings) -> str:
    api_url = (settings.asr_api_url or "").strip()
    api_key = (settings.asr_api_key or "").strip()
    model_name = (settings.qwen_voice_model_path or settings.asr_model_path or "").strip() or "qwen/qwenasr-0.6b"

    if not api_url:
        raise VoiceError("ASR API URL is empty.")
    if not api_key:
        raise VoiceError("ASR API key is empty.")

    headers = {"Authorization": f"Bearer {api_key}"}
    data = {"model": model_name}
    language = (settings.asr_language or "").strip()
    if language and language.lower() != "auto":
        data["language"] = language

    with audio_path.open("rb") as fh:
        files = {"file": (audio_path.name, fh, "audio/wav")}
        try:
            resp = requests.post(api_url, headers=headers, data=data, files=files, timeout=180)
        except requests.RequestException as exc:
            raise VoiceError(f"ASR API request failed: {exc}") from exc

    if resp.status_code != 200:
        detail = resp.text[:600]
        raise VoiceError(f"ASR API error {resp.status_code}: {detail}")

    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"ASR API returned non-JSON response: {resp.text[:300]}") from exc

    text = _extract_transcript_text(payload)
    if not text:
        sample = str(payload)[:500]
        raise VoiceError(
            "ASR API returned no transcript text in known fields "
            "(text/transcript/transcription/choices). "
            f"Response sample: {sample}"
        )
    return text


def _extract_transcript_text(payload: object) -> str:
    """Extract transcript text from common ASR/OpenAI-compatible payload shapes."""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""

    direct_keys = ("text", "transcript", "transcription", "output_text", "result")
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested_text = _extract_transcript_text(value)
            if nested_text:
                return nested_text

    # OpenAI-style choices arrays or custom nested segments.
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, str) and choice.strip():
                return choice.strip()
            if isinstance(choice, dict):
                for key in ("text", "transcript", "content"):
                    value = choice.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        text = _extract_transcript_text(data)
        if text:
            return text

    segments = payload.get("segments")
    if isinstance(segments, list):
        joined = []
        for seg in segments:
            if isinstance(seg, dict):
                value = seg.get("text") or seg.get("transcript")
                if isinstance(value, str) and value.strip():
                    joined.append(value.strip())
        if joined:
            return " ".join(joined)

    return ""