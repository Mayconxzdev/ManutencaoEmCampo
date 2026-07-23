"""Transcrição de áudio com backends plugáveis.

Versões anteriores dependiam exclusivamente da API OpenAI. Este módulo mantém
compatibilidade com esse modo e usa caminhos locais opcionais:

- faster-whisper/CTranslate2 para servidor Python local;
- whisper.cpp por binário/CLI, útil em Windows sem GPU;
- Vibe por servidor HTTP local quando iniciado com API;
- fallback manual quando nada estiver configurado.

Nenhuma dependência pesada é obrigatória no pacote base. Os backends locais são
ativados por variável de ambiente e só são importados/executados quando usados.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_WHISPER_MODEL_CACHE: dict[tuple[str, str, str], object] = {}


def _text(value: Optional[str]) -> str:
    return (value or "").strip()


def truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "sim"}


@dataclass(slots=True)
class TranscriptionResult:
    text: Optional[str]
    status: str
    error: Optional[str] = None
    backend: Optional[str] = None

    def as_tuple(self) -> tuple[Optional[str], str, Optional[str]]:
        return self.text, self.status, self.error


def configured_backend() -> str:
    return os.getenv("MEC_TRANSCRIPTION_BACKEND", "auto").strip().lower() or "auto"


def capabilities() -> dict:
    """Retorna capacidade real sem baixar modelos nem testar áudio."""
    import importlib.util
    import shutil

    whisper_cpp_bin = os.getenv("MEC_WHISPER_CPP_BIN", "").strip()
    vibe_url = os.getenv("MEC_VIBE_API_URL", "").strip()
    return {
        "enabled": truthy_env("MEC_TRANSCRIPTION_ENABLED"),
        "backend": configured_backend(),
        "language": os.getenv("MEC_TRANSCRIPTION_LANGUAGE", "pt"),
        "openai": {
            "available": bool(os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("MEC_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
        },
        "faster_whisper": {
            "available": importlib.util.find_spec("faster_whisper") is not None,
            "model": os.getenv("MEC_LOCAL_WHISPER_MODEL", "small"),
            "device": os.getenv("MEC_LOCAL_WHISPER_DEVICE", "cpu"),
            "compute_type": os.getenv("MEC_LOCAL_WHISPER_COMPUTE", "int8"),
        },
        "whisper_cpp": {
            "available": bool(whisper_cpp_bin and (Path(whisper_cpp_bin).exists() or shutil.which(whisper_cpp_bin))),
            "bin": whisper_cpp_bin,
            "model": os.getenv("MEC_WHISPER_CPP_MODEL", ""),
        },
        "vibe": {
            "available": bool(vibe_url),
            "url": vibe_url,
        },
    }


def _transcribe_openai(path: Path) -> TranscriptionResult:
    if not os.getenv("OPENAI_API_KEY"):
        return TranscriptionResult(None, "stored_without_transcription", "OPENAI_API_KEY não configurada.", "openai")
    try:
        from openai import OpenAI

        model = os.getenv("MEC_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
        client = OpenAI()
        with path.open("rb") as audio_file:
            result = client.audio.transcriptions.create(model=model, file=audio_file)
        text = getattr(result, "text", None)
        if not text and isinstance(result, dict):
            text = result.get("text")
        value = _text(text)
        if value:
            return TranscriptionResult(value, "transcribed", None, "openai")
        return TranscriptionResult(None, "stored_without_transcription", "Serviço de transcrição não retornou texto.", "openai")
    except Exception as exc:  # pragma: no cover - depende de serviço externo
        return TranscriptionResult(None, "stored_without_transcription", f"Falha na transcrição OpenAI: {exc}", "openai")


def _transcribe_faster_whisper(path: Path) -> TranscriptionResult:
    try:
        from faster_whisper import WhisperModel

        model_name = os.getenv("MEC_LOCAL_WHISPER_MODEL", "small")
        device = os.getenv("MEC_LOCAL_WHISPER_DEVICE", "cpu")
        compute_type = os.getenv("MEC_LOCAL_WHISPER_COMPUTE", "int8")
        language = os.getenv("MEC_TRANSCRIPTION_LANGUAGE", "pt") or None
        beam_size = int(os.getenv("MEC_LOCAL_WHISPER_BEAM_SIZE", "5"))
        no_speech_threshold = float(os.getenv("MEC_LOCAL_WHISPER_NO_SPEECH_THRESHOLD", "0.6"))
        log_prob_threshold = float(os.getenv("MEC_LOCAL_WHISPER_LOG_PROB_THRESHOLD", "-1.0"))
        compression_ratio_threshold = float(os.getenv("MEC_LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.4"))
        vad_filter = truthy_env("MEC_LOCAL_WHISPER_VAD")
        cache_key = (model_name, device, compute_type)
        model = _WHISPER_MODEL_CACHE.get(cache_key)
        if model is None:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            _WHISPER_MODEL_CACHE[cache_key] = model
        try:
            segments, _info = model.transcribe(
                str(path),
                language=language,
                task="transcribe",
                beam_size=beam_size,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=vad_filter,
                no_speech_threshold=no_speech_threshold,
                log_prob_threshold=log_prob_threshold,
                compression_ratio_threshold=compression_ratio_threshold,
            )
        except TypeError:
            segments, _info = model.transcribe(str(path), language=language, beam_size=beam_size)
        value = _text(" ".join(_text(segment.text) for segment in segments))
        if value:
            return TranscriptionResult(value, "transcribed", None, "faster_whisper")
        return TranscriptionResult(None, "stored_without_transcription", "faster-whisper não retornou texto.", "faster_whisper")
    except ImportError:
        return TranscriptionResult(None, "stored_without_transcription", "Pacote faster-whisper não instalado.", "faster_whisper")
    except Exception as exc:  # pragma: no cover - depende de modelo/hardware
        return TranscriptionResult(None, "stored_without_transcription", f"Falha no faster-whisper local: {exc}", "faster_whisper")


def _transcribe_whisper_cpp(path: Path) -> TranscriptionResult:
    bin_path = os.getenv("MEC_WHISPER_CPP_BIN", "").strip()
    model_path = os.getenv("MEC_WHISPER_CPP_MODEL", "").strip()
    if not bin_path:
        return TranscriptionResult(None, "stored_without_transcription", "MEC_WHISPER_CPP_BIN não configurado.", "whisper_cpp")
    if not model_path:
        return TranscriptionResult(None, "stored_without_transcription", "MEC_WHISPER_CPP_MODEL não configurado.", "whisper_cpp")
    language = os.getenv("MEC_TRANSCRIPTION_LANGUAGE", "pt")
    timeout = int(os.getenv("MEC_TRANSCRIPTION_TIMEOUT_SECONDS", "600"))
    extra_args = shlex.split(os.getenv("MEC_WHISPER_CPP_ARGS", ""))
    try:
        with tempfile.TemporaryDirectory(prefix="mec_whisper_") as tmp:
            out_base = str(Path(tmp) / "transcript")
            command = [bin_path, "-m", model_path, "-f", str(path), "-l", language, "-otxt", "-of", out_base, *extra_args]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            txt_file = Path(f"{out_base}.txt")
            value = _text(txt_file.read_text(encoding="utf-8", errors="ignore") if txt_file.exists() else completed.stdout)
            if value:
                return TranscriptionResult(value, "transcribed", None, "whisper_cpp")
            error = _text(completed.stderr) or f"whisper.cpp retornou código {completed.returncode}."
            return TranscriptionResult(None, "stored_without_transcription", error, "whisper_cpp")
    except Exception as exc:  # pragma: no cover - depende de binário externo
        return TranscriptionResult(None, "stored_without_transcription", f"Falha no whisper.cpp: {exc}", "whisper_cpp")


def _transcribe_vibe(path: Path) -> TranscriptionResult:
    base_url = os.getenv("MEC_VIBE_API_URL", "").strip().rstrip("/")
    if not base_url:
        return TranscriptionResult(None, "stored_without_transcription", "MEC_VIBE_API_URL não configurado.", "vibe")
    model = os.getenv("MEC_VIBE_MODEL", os.getenv("MEC_LOCAL_WHISPER_MODEL", "small"))
    language = os.getenv("MEC_TRANSCRIPTION_LANGUAGE", "pt")
    timeout = float(os.getenv("MEC_TRANSCRIPTION_TIMEOUT_SECONDS", "600"))
    try:
        import httpx

        endpoints = [
            f"{base_url}/v1/audio/transcriptions",
            f"{base_url}/audio/transcriptions",
            f"{base_url}/transcribe",
        ]
        last_error = None
        for endpoint in endpoints:
            try:
                with path.open("rb") as audio_file:
                    files = {"file": (path.name, audio_file, "application/octet-stream")}
                    data = {"model": model, "language": language}
                    response = httpx.post(endpoint, files=files, data=data, timeout=timeout)
                if response.status_code >= 400:
                    last_error = f"{endpoint}: HTTP {response.status_code} {response.text[:300]}"
                    continue
                payload = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text}
                value = _text(payload.get("text") or payload.get("transcript") or payload.get("result"))
                if value:
                    return TranscriptionResult(value, "transcribed", None, "vibe")
                last_error = f"{endpoint}: resposta sem texto."
            except Exception as exc:
                last_error = f"{endpoint}: {exc}"
        return TranscriptionResult(None, "stored_without_transcription", last_error or "Vibe não retornou texto.", "vibe")
    except ImportError:
        return TranscriptionResult(None, "stored_without_transcription", "Pacote httpx não instalado.", "vibe")


def transcribe_audio(path: Path) -> TranscriptionResult:
    """Executa transcrição conforme ambiente, sem quebrar o fluxo da OM."""
    if not truthy_env("MEC_TRANSCRIPTION_ENABLED"):
        return TranscriptionResult(None, "stored_without_transcription", "Transcrição automática desabilitada.", configured_backend())

    backend = configured_backend()
    if backend == "none":
        return TranscriptionResult(None, "stored_without_transcription", "Backend de transcrição definido como none.", backend)
    if backend == "openai":
        return _transcribe_openai(path)
    if backend in {"faster_whisper", "faster-whisper", "local"}:
        return _transcribe_faster_whisper(path)
    if backend in {"whisper_cpp", "whisper.cpp", "cpp"}:
        return _transcribe_whisper_cpp(path)
    if backend == "vibe":
        return _transcribe_vibe(path)

    # auto: preferir nuvem já configurada; depois opções locais explícitas.
    attempts: list[TranscriptionResult] = []
    if os.getenv("OPENAI_API_KEY"):
        result = _transcribe_openai(path)
        if result.text:
            return result
        attempts.append(result)
    if os.getenv("MEC_WHISPER_CPP_BIN") and os.getenv("MEC_WHISPER_CPP_MODEL"):
        result = _transcribe_whisper_cpp(path)
        if result.text:
            return result
        attempts.append(result)
    if os.getenv("MEC_VIBE_API_URL"):
        result = _transcribe_vibe(path)
        if result.text:
            return result
        attempts.append(result)
    # faster-whisper só é tentado automaticamente se o usuário marcou para evitar download acidental de modelo.
    if truthy_env("MEC_LOCAL_WHISPER_AUTO"):
        result = _transcribe_faster_whisper(path)
        if result.text:
            return result
        attempts.append(result)

    errors = "; ".join(_text(item.error) for item in attempts if item.error)
    return TranscriptionResult(None, "stored_without_transcription", errors or "Nenhum backend de transcrição configurado.", "auto")
