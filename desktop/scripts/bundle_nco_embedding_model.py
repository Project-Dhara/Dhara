#!/usr/bin/env python3
"""Download, verify, smoke-test, and pre-index the desktop NCO embedding model.

Driven by ``embeddinggemma-300m-pin.json`` (default). Build machines need
``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN`` because EmbeddingGemma is gated.

Usage::

    python desktop/scripts/bundle_nco_embedding_model.py \\
      --out desktop/resources/win-x64/models/embeddinggemma-300m
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PIN_PATH = SCRIPT_DIR / "embeddinggemma-300m-pin.json"
MANIFEST_PATH = SCRIPT_DIR / "embeddinggemma-300m.manifest.json"
_SKIP_SUFFIXES = (".lock",)
_SKIP_NAMES = frozenset({".gitattributes", "README.md", ".cache", "notebook.ipynb"})
_PRUNE_AFTER_DOWNLOAD = (".gitattributes", "README.md", "notebook.ipynb")


def _load_pin() -> dict:
    return json.loads(PIN_PATH.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_model_files(model_dir: Path):
    for path in sorted(model_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(model_dir).as_posix()
        name = path.name
        if name in _SKIP_NAMES:
            continue
        if name.startswith(".") and name not in ("config.json", "modules.json"):
            continue
        if any(name.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        if rel.startswith(".cache/") or "/.cache/" in rel:
            continue
        # Prebuilt index is generated locally — not part of Hub manifest.
        if name in ("nco_index.npz", "nco_index.meta.json"):
            continue
        yield rel, path


def build_manifest(model_dir: Path, pin: dict) -> dict:
    files = {rel: _sha256_file(path) for rel, path in _iter_model_files(model_dir)}
    return {
        "repo_id": pin["repo_id"],
        "revision": pin["revision"],
        "dim": pin["dim"],
        "files": files,
    }


def verify_manifest(model_dir: Path, manifest: dict) -> None:
    expected = manifest.get("files") or {}
    if not expected:
        raise SystemExit("Manifest has no files")
    missing = []
    mismatch = []
    for rel, want in expected.items():
        path = model_dir / rel
        if not path.is_file():
            missing.append(rel)
            continue
        got = _sha256_file(path)
        if got.lower() != str(want).lower():
            mismatch.append(f"{rel}: expected {want}, got {got}")
    if missing or mismatch:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing[:20]))
        if mismatch:
            parts.append("mismatch: " + "; ".join(mismatch[:10]))
        raise SystemExit("Embedding model verification failed — " + " | ".join(parts))


def _require_hf_token() -> str:
    token = (
        (os.environ.get("HF_TOKEN") or "").strip()
        or (os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    )
    if not token:
        raise SystemExit(
            "HF_TOKEN (or HUGGING_FACE_HUB_TOKEN) is required to download "
            "google/embeddinggemma-300m (gated model). Accept the license on "
            "Hugging Face, then set the token for prepare-backend."
        )
    return token


def download_model(out_dir: Path, pin: dict, cache_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    token = _require_hf_token()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=pin["repo_id"],
            revision=pin["revision"],
            local_dir=str(out_dir),
            cache_dir=str(cache_dir),
            token=token,
        )
    except Exception as e:
        raise SystemExit(
            f"Failed to download {pin['repo_id']}@{pin['revision']}: {e}\n"
            "Ensure HF_TOKEN is valid and the EmbeddingGemma license was accepted."
        ) from e
    for name in _PRUNE_AFTER_DOWNLOAD:
        p = out_dir / name
        if p.is_file():
            p.unlink()


def smoke_encode(model_dir: Path, dim: int) -> None:
    # Keep token available for local_files_only loads that still touch hub metadata.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        str(model_dir),
        trust_remote_code=True,
        local_files_only=True,
        device="cpu",
    )
    vecs = model.encode(
        ["software engineer", "farm worker"],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    if getattr(vecs, "shape", None) is None or len(vecs) != 2:
        raise SystemExit(f"Smoke encode failed: unexpected result {type(vecs)}")
    width = int(vecs.shape[1]) if hasattr(vecs, "shape") else len(vecs[0])
    if width != dim:
        raise SystemExit(f"Smoke encode dim {width} != expected {dim}")
    print(f"smoke ok: encoded 2 texts → dim={width} (torch {torch.__version__})")


def build_nco_index(model_dir: Path, nco_csv: Path, pin: dict) -> Path:
    import csv
    import hashlib

    import numpy as np
    from sentence_transformers import SentenceTransformer

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    rows = []
    with nco_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            code = (raw.get("NCO_2015_Code") or "").strip()
            title = (raw.get("Occupation_Title") or "").strip()
            if not code or not title:
                continue
            search_text = " | ".join(
                filter(
                    None,
                    [
                        title,
                        (raw.get("Family_Title") or "").strip(),
                        (raw.get("Group_Title") or "").strip(),
                        (raw.get("SubDivision_Title") or "").strip(),
                        (raw.get("Division_Title") or "").strip(),
                    ],
                )
            )
            rows.append({"nco_code": code, "search_text": search_text, "title": title})

    if not rows:
        raise SystemExit(f"No NCO rows in {nco_csv}")

    nco_sha = hashlib.sha256(nco_csv.read_bytes()).hexdigest()
    model = SentenceTransformer(
        str(model_dir),
        trust_remote_code=True,
        local_files_only=True,
        device="cpu",
    )
    texts = [r["search_text"] for r in rows]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=32,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2 or embeddings.shape[1] != int(pin["dim"]):
        raise SystemExit(f"Bad embedding shape {embeddings.shape}")

    out = model_dir / "nco_index.npz"
    meta = {
        "model": pin["repo_id"],
        "revision": pin["revision"],
        "nco_sha256": nco_sha,
        "dim": int(pin["dim"]),
        "count": len(rows),
        "family": pin.get("family") or "embeddinggemma",
    }
    np.savez_compressed(
        out,
        embeddings=embeddings,
        codes=np.asarray([r["nco_code"] for r in rows], dtype=object),
        titles=np.asarray([r["title"] for r in rows], dtype=object),
        meta_json=np.asarray(json.dumps(meta)),
    )
    (model_dir / "nco_index.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {out} ({embeddings.shape[0]} x {embeddings.shape[1]})")

    # Hierarchy node embeddings (division/subdivision/group/family) — avoids
    # live encode on first Suggest after cold start.
    hier_docs = []
    seen = set()
    specs = (
        ("division",),
        ("subdivision",),
        ("group",),
        ("family",),
    )
    with nco_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            for level_tuple in specs:
                level = level_tuple[0]
                # Map CSV columns to hierarchy levels.
                col_map = {
                    "division": ("Division_Code", "Division_Title"),
                    "subdivision": ("SubDivision_Code", "SubDivision_Title"),
                    "group": ("Group_Code", "Group_Title"),
                    "family": ("Family_Code", "Family_Title"),
                }
                code_col, title_col = col_map[level]
                code = (raw.get(code_col) or "").strip()
                title = (raw.get(title_col) or "").strip()
                if not code or not title or (level, code) in seen:
                    continue
                seen.add((level, code))
                titles = []
                for lv in ("division", "subdivision", "group", "family"):
                    _, tc = col_map[lv]
                    t = (raw.get(tc) or "").strip()
                    if t and (
                        lv == "division"
                        or (lv == "subdivision" and level in ("subdivision", "group", "family"))
                        or (lv == "group" and level in ("group", "family"))
                        or (lv == "family" and level == "family")
                    ):
                        titles.append(t)
                hier_docs.append(
                    {
                        "key": f"{level}:{code}",
                        "search_text": " | ".join(dict.fromkeys(titles)) or title,
                    }
                )
    if hier_docs:
        hier_emb = model.encode(
            [d["search_text"] for d in hier_docs],
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=32,
        )
        hier_emb = np.asarray(hier_emb, dtype=np.float32)
        hier_out = model_dir / "nco_hierarchy_index.npz"
        np.savez_compressed(
            hier_out,
            embeddings=hier_emb,
            keys=np.asarray([d["key"] for d in hier_docs], dtype=object),
            meta_json=np.asarray(json.dumps({**meta, "kind": "hierarchy", "count": len(hier_docs)})),
        )
        print(f"wrote {hier_out} ({hier_emb.shape[0]} x {hier_emb.shape[1]})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True, help="Model output directory")
    ap.add_argument(
        "--cache",
        type=Path,
        default=SCRIPT_DIR.parent / ".cache" / "models",
        help="HF cache root",
    )
    ap.add_argument("--write-manifest", action="store_true")
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-index", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument(
        "--nco-csv",
        type=Path,
        default=SCRIPT_DIR.parent.parent / "backend" / "data" / "nco_2015_concordance.csv",
    )
    args = ap.parse_args()
    pin = _load_pin()
    out_dir = args.out.resolve()

    if args.smoke_only:
        smoke_encode(out_dir, int(pin["dim"]))
        return 0

    if not args.skip_download:
        print(f"Downloading {pin['repo_id']}@{pin['revision']} → {out_dir}")
        download_model(out_dir, pin, args.cache.resolve())

    if args.write_manifest or not MANIFEST_PATH.is_file():
        manifest = build_manifest(out_dir, pin)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote manifest {MANIFEST_PATH} ({len(manifest['files'])} files)")
    else:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest.get("revision") != pin["revision"]:
            raise SystemExit(
                f"Manifest revision {manifest.get('revision')} != pin {pin['revision']}"
            )
        verify_manifest(out_dir, manifest)
        print(f"Verified {len(manifest['files'])} files against manifest")

    if not args.skip_smoke:
        smoke_encode(out_dir, int(pin["dim"]))
    else:
        print("Skipping smoke encode (--skip-smoke)")

    if not args.skip_index:
        if not args.nco_csv.is_file():
            raise SystemExit(f"NCO CSV missing: {args.nco_csv}")
        build_nco_index(out_dir, args.nco_csv.resolve(), pin)

    return 0


if __name__ == "__main__":
    sys.exit(main())
