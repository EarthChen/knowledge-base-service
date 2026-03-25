"""Embedding generator for code snippets and documents.

Uses sentence-transformers to generate dense vector embeddings
for semantic search over code and documentation.
Default model: nomic-ai/CodeRankEmbed (code retrieval SOTA, 137M params, 8192 context).

Supports two backends:
  - "onnx"  (default): onnxruntime + transformers tokenizer — ~50MB runtime, no PyTorch
  - "torch": sentence-transformers + PyTorch — ~1.5GB runtime, supports MPS/CUDA
"""

from __future__ import annotations

import asyncio
import gc
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING

import numpy as np

from config import EmbeddingConfig
from log import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


def _format_code_text(name: str, signature: str, docstring: str, code_snippet: str) -> str:
    """Build a concise textual representation for embedding."""
    parts = []
    if name:
        parts.append(f"Name: {name}")
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring:
        parts.append(f"Description: {docstring[:500]}")
    if code_snippet:
        parts.append(f"Code: {code_snippet[:1000]}")
    return "\n".join(parts)


def _iter_chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _flush_accelerator_cache() -> None:
    """Release cached memory from MPS / CUDA accelerators."""
    try:
        import torch

        if hasattr(torch, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    gc.collect()


class _EmbeddingBackend(ABC):
    """Abstract backend interface for embedding generation."""

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def encode(self, texts: list[str], batch_size: int) -> np.ndarray: ...

    @abstractmethod
    def unload(self) -> None: ...


class _OnnxBackend(_EmbeddingBackend):
    """ONNX Runtime backend — minimal memory footprint, no PyTorch required."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._session = None
        self._tokenizer = None

    def load(self) -> None:
        if self._session is not None:
            return

        import onnxruntime as ort
        from transformers import AutoTokenizer

        log.info("onnx_backend_loading", model=self._config.model_name)

        self._tokenizer = AutoTokenizer.from_pretrained(self._config.model_name)

        onnx_path = self._config.onnx_path
        if not onnx_path:
            onnx_path = self._resolve_onnx_path()

        providers = self._select_providers()
        self._session = ort.InferenceSession(onnx_path, providers=providers)

        log.info(
            "onnx_backend_loaded",
            path=onnx_path,
            providers=[p if isinstance(p, str) else p[0] for p in providers],
        )

    def _resolve_onnx_path(self) -> str:
        """Locate or download the ONNX model file."""
        from pathlib import Path

        from huggingface_hub import hf_hub_download, try_to_load_from_cache

        onnx_repo = f"{self._config.model_name}"
        onnx_filename = "model.onnx"

        cached = try_to_load_from_cache(onnx_repo, onnx_filename)
        if isinstance(cached, str) and Path(cached).is_file():
            return cached

        try:
            return hf_hub_download(onnx_repo, onnx_filename)
        except Exception:
            pass

        community_repo = "sirasagi62/code-rank-embed-onnx"
        log.info("onnx_trying_community_repo", repo=community_repo)
        try:
            return hf_hub_download(community_repo, "model.onnx")
        except Exception:
            pass

        log.warning("onnx_not_found_exporting", model=self._config.model_name)
        return self._export_to_onnx()

    def _export_to_onnx(self) -> str:
        """One-time export from PyTorch to ONNX (requires torch + sentence-transformers)."""
        from pathlib import Path

        cache_dir = Path.home() / ".cache" / "kb-onnx-models" / self._config.model_name.replace("/", "--")
        onnx_path = cache_dir / "model.onnx"
        if onnx_path.is_file():
            return str(onnx_path)

        cache_dir.mkdir(parents=True, exist_ok=True)

        import torch
        from sentence_transformers import SentenceTransformer

        log.info("onnx_exporting_model", model=self._config.model_name)
        st_model = SentenceTransformer(
            self._config.model_name,
            device="cpu",
            trust_remote_code=self._config.trust_remote_code,
        )

        transformer_module = st_model[0]
        hf_model = transformer_module.auto_model
        hf_model.eval()

        dummy_input = self._tokenizer(
            "dummy text", return_tensors="pt", padding="max_length", max_length=32, truncation=True,
        )

        torch.onnx.export(
            hf_model,
            (dummy_input["input_ids"], dummy_input["attention_mask"]),
            str(onnx_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "last_hidden_state": {0: "batch", 1: "seq"},
            },
            opset_version=17,
        )

        del st_model, hf_model, transformer_module, dummy_input
        _flush_accelerator_cache()

        log.info("onnx_export_complete", path=str(onnx_path))
        return str(onnx_path)

    def _select_providers(self) -> list:
        import onnxruntime as ort

        available = ort.get_available_providers()
        device = self._config.device

        if device == "cpu":
            return ["CPUExecutionProvider"]

        providers: list = []
        if device in ("auto", "coreml") and "CoreMLExecutionProvider" in available:
            providers.append(("CoreMLExecutionProvider", {"ModelFormat": "MLProgram"}))
        if device in ("auto", "cuda") and "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        return providers

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        self.load()
        assert self._tokenizer is not None
        assert self._session is not None

        all_embeddings: list[np.ndarray] = []

        for chunk in _iter_chunks(texts, batch_size):
            inputs = self._tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=self._config.max_length,
                return_tensors="np",
            )

            input_feed = {
                "input_ids": inputs["input_ids"].astype(np.int64),
                "attention_mask": inputs["attention_mask"].astype(np.int64),
            }
            outputs = self._session.run(None, input_feed)
            token_embeddings = outputs[0]

            attention_mask = inputs["attention_mask"].astype(np.float32)
            mask_expanded = np.expand_dims(attention_mask, axis=-1)
            sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask

            norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
            normalized = mean_pooled / np.maximum(norms, 1e-12)

            all_embeddings.append(normalized)

        return np.vstack(all_embeddings) if all_embeddings else np.empty((0, self._config.dimension))

    def unload(self) -> None:
        self._session = None
        self._tokenizer = None
        gc.collect()
        log.info("onnx_backend_unloaded")


class _TorchBackend(_EmbeddingBackend):
    """sentence-transformers + PyTorch backend."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return

        from sentence_transformers import SentenceTransformer

        device = self._config.resolve_device()
        log.info("torch_backend_loading", model=self._config.model_name, device=device)
        self._model = SentenceTransformer(
            self._config.model_name,
            device=device,
            trust_remote_code=self._config.trust_remote_code,
        )
        if self._config.use_fp16 and device != "cpu":
            self._model.half()
            log.info("torch_backend_using_fp16", device=device)
        log.info("torch_backend_loaded", dimension=self._config.dimension, device=device)

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        self.load()
        assert self._model is not None

        all_embeddings: list[np.ndarray] = []

        for chunk in _iter_chunks(texts, batch_size):
            embeddings = self._model.encode(
                chunk,
                batch_size=batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            all_embeddings.append(embeddings)
            _flush_accelerator_cache()

        return np.vstack(all_embeddings) if all_embeddings else np.empty((0, self._config.dimension))

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            _flush_accelerator_cache()
            log.info("torch_backend_unloaded")


class EmbeddingGenerator:
    """Generates embeddings using a configurable backend (ONNX or PyTorch)."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._backend: _EmbeddingBackend | None = None

    def _get_backend(self) -> _EmbeddingBackend:
        if self._backend is None:
            if self._config.backend == "onnx":
                self._backend = _OnnxBackend(self._config)
            else:
                self._backend = _TorchBackend(self._config)
        return self._backend

    def unload_model(self) -> None:
        """Explicitly release model memory."""
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    async def generate(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_batch, texts, is_query)

    def _encode_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        backend = self._get_backend()
        if is_query and self._config.query_prefix:
            texts = [f"{self._config.query_prefix}{t}" for t in texts]

        chunk_size = self._config.chunk_size
        all_results: list[list[float]] = []

        for chunk in _iter_chunks(texts, chunk_size):
            embeddings = backend.encode(chunk, batch_size=self._config.batch_size)
            all_results.extend(row.tolist() for row in embeddings)

        return all_results

    async def generate_for_query(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for search queries (with instruction prefix)."""
        return await self.generate(texts, is_query=True)

    async def generate_for_code(
        self,
        items: list[dict[str, str]],
    ) -> list[list[float]]:
        """Generate embeddings for code items (functions/classes)."""
        texts = [
            _format_code_text(
                item.get("name", ""),
                item.get("signature", ""),
                item.get("docstring", ""),
                item.get("code_snippet", ""),
            )
            for item in items
        ]
        return await self.generate(texts, is_query=False)

    @property
    def dimension(self) -> int:
        return self._config.dimension
