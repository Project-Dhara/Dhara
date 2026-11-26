"""Local NCO embedding model lifecycle (desktop BGE + Docker EmbeddingGemma)."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_EMBEDDER = None
_EMBEDDER_TRIED = False
_EMBEDDER_LAST_USED = 0.0
_EMBEDDER_LOCK = threading.Lock()
_LAST_MODE = "keyword-only"  # semantic | keyword-only
_LAST_REASON = ""
_IDLE_TIMER: Optional[threading.Timer] = None

# Default: unload ~8 minutes after last encode.
_IDLE_SEC = float(os.environ.get("NCO_EMBEDDING_IDLE_SEC") or "480")
# Need this much free RAM before loading (MB).
_MIN_RAM_MB = int(os.environ.get("NCO_EMBEDDING_MIN_RAM_MB") or "900")


def embedding_family() -> str:
    explicit = (os.environ.get("NCO_EMBEDDING_FAMILY") or "").strip().lower()
    if explicit:
        return explicit
    name = (os.environ.get("NCO_EMBEDDING_MODEL") or "").strip().lower()
    if "bge" in name:
        return "bge"
    if "embeddinggemma" in name or "gemma" in name:
        return "embeddinggemma"
    return ""


def query_text_for_encode(text: str) -> str:
    """Apply model-specific retrieval instruction to queries only (not passages)."""
    raw = str(text or "")
    if embedding_family() == "bge":
        if raw.startswith(BGE_QUERY_PREFIX):
            return raw
        return BGE_QUERY_PREFIX + raw
    return raw


def retrieval_status() -> dict[str, str]:
    return {"retrieval_mode": _LAST_MODE, "retrieval_reason": _LAST_REASON}


def set_retrieval_status(mode: str, reason: str = "") -> None:
    global _LAST_MODE, _LAST_REASON
    _LAST_MODE = mode
    _LAST_REASON = reason or ""


def clear_embedder() -> None:
    global _EMBEDDER, _EMBEDDER_TRIED, _EMBEDDER_LAST_USED, _IDLE_TIMER
    with _EMBEDDER_LOCK:
        if _IDLE_TIMER is not None:
            try:
                _IDLE_TIMER.cancel()
            except Exception:
                pass
            _IDLE_TIMER = None
        _EMBEDDER = None
        _EMBEDDER_TRIED = False
        _EMBEDDER_LAST_USED = 0.0


def _schedule_idle_unload() -> None:
    global _IDLE_TIMER
    if _IDLE_SEC <= 0:
        return

    def _fire() -> None:
        global _EMBEDDER, _EMBEDDER_LAST_USED
        with _EMBEDDER_LOCK:
            idle_for = time.monotonic() - _EMBEDDER_LAST_USED
            if _EMBEDDER is not None and idle_for >= (_IDLE_SEC - 1.0):
                logger.info("Unloading NCO embedding model after %.0fs idle", idle_for)
                _EMBEDDER = None
                # Allow a later request to try again.
                global _EMBEDDER_TRIED
                _EMBEDDER_TRIED = False

    with _EMBEDDER_LOCK:
        if _IDLE_TIMER is not None:
            try:
                _IDLE_TIMER.cancel()
            except Exception:
                pass
        _IDLE_TIMER = threading.Timer(_IDLE_SEC, _fire)
        _IDLE_TIMER.daemon = True
        _IDLE_TIMER.start()


def _available_ram_mb() -> Optional[int]:
    try:
        from app.services.llm_prompts import _available_ram_mb as _ram

        return _ram()
    except Exception:
        return None


def _ram_ok() -> tuple[bool, str]:
    avail = _available_ram_mb()
    if avail is None:
        return True, ""
    if avail < _MIN_RAM_MB:
        return False, f"only {avail} MB RAM available (need {_MIN_RAM_MB} MB for embeddings)"
    return True, ""


def touch_embedder_used() -> None:
    global _EMBEDDER_LAST_USED
    _EMBEDDER_LAST_USED = time.monotonic()
    _schedule_idle_unload()


def load_embedder() -> Any:
    """Lazy-load SentenceTransformer from NCO_EMBEDDING_MODEL (path or Hub id)."""
    global _EMBEDDER, _EMBEDDER_TRIED, _EMBEDDER_LAST_USED

    with _EMBEDDER_LOCK:
        if _EMBEDDER is not None:
            return _EMBEDDER
        if _EMBEDDER_TRIED:
            return None
        _EMBEDDER_TRIED = True

    name = (os.environ.get("NCO_EMBEDDING_MODEL") or "").strip()
    if not name:
        set_retrieval_status("keyword-only", "NCO_EMBEDDING_MODEL unset")
        return None

    ok, reason = _ram_ok()
    if not ok:
        logger.warning("Skipping NCO embedder load: %s", reason)
        set_retrieval_status("keyword-only", reason)
        with _EMBEDDER_LOCK:
            _EMBEDDER_TRIED = False  # retry when RAM recovers
        return None

    try:
        import torch
        from sentence_transformers import SentenceTransformer

        path = Path(name)
        local_only = path.is_dir()
        # Desktop enforces offline Hub; Hub ids (Docker) may still download.
        offline = (os.environ.get("HF_HUB_OFFLINE") or "").strip() in ("1", "true", "yes")
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        kwargs = {
            "trust_remote_code": True,
            "model_kwargs": {
                "torch_dtype": dtype,
                "low_cpu_mem_usage": True,
            },
        }
        if local_only or offline:
            kwargs["local_files_only"] = True
        if token and not local_only and not offline:
            kwargs["token"] = token

        model = SentenceTransformer(name, **kwargs)
        if not torch.cuda.is_available():
            model = model.to("cpu")

        with _EMBEDDER_LOCK:
            _EMBEDDER = model
            _EMBEDDER_LAST_USED = time.monotonic()
        set_retrieval_status("semantic", "")
        _schedule_idle_unload()
        logger.info("Loaded NCO embedding model from %s", name)
        return model
    except Exception as e:
        logger.warning("Failed to load NCO embedding model (%s): %s", name, e)
        set_retrieval_status("keyword-only", str(e).strip() or e.__class__.__name__)
        with _EMBEDDER_LOCK:
            _EMBEDDER = None
        return None


def prebuilt_index_path() -> Optional[Path]:
    """nco_index.npz next to a local model folder, if present."""
    name = (os.environ.get("NCO_EMBEDDING_MODEL") or "").strip()
    if not name:
        return None
    path = Path(name)
    if path.is_dir():
        candidate = path / "nco_index.npz"
        if candidate.is_file():
            return candidate
    # Also check sibling models/embeddinggemma… under DHARA desktop runtime.
    backend_dir = (os.environ.get("DHARA_BACKEND_DIR") or "").strip()
    if backend_dir:
        alt = (
            Path(backend_dir).parent
            / "models"
            / "embeddinggemma-300m"
            / "nco_index.npz"
        )
        if alt.is_file():
            return alt
    return None


def load_prebuilt_occupation_embeddings(doc_codes: list[str]):
    """Return float matrix aligned to doc_codes, or None if missing/mismatched."""
    path = prebuilt_index_path()
    if path is None:
        return None
    try:
        import json

        import numpy as np

        data = np.load(path, allow_pickle=True)
        codes = [str(c) for c in data["codes"].tolist()]
        embeddings = data["embeddings"]
        meta_raw = data.get("meta_json")
        if meta_raw is not None:
            meta = json.loads(str(meta_raw.item() if hasattr(meta_raw, "item") else meta_raw))
            pin_rev = (os.environ.get("NCO_EMBEDDING_REVISION") or "").strip()
            if pin_rev and meta.get("revision") and meta["revision"] != pin_rev:
                logger.warning(
                    "Prebuilt NCO index revision %s != env %s — ignoring",
                    meta.get("revision"),
                    pin_rev,
                )
                return None
        if codes != list(doc_codes):
            # Allow reordering by code map when lengths match and sets equal.
            if len(codes) != len(doc_codes) or set(codes) != set(doc_codes):
                logger.warning(
                    "Prebuilt NCO index code list mismatch (%s vs %s docs) — ignoring",
                    len(codes),
                    len(doc_codes),
                )
                return None
            index_of = {c: i for i, c in enumerate(codes)}
            order = [index_of[c] for c in doc_codes]
            embeddings = embeddings[order]
        return embeddings
    except Exception as e:
        logger.warning("Could not load prebuilt NCO index %s: %s", path, e)
        return None
