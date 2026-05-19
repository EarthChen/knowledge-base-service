"""Embedding generator for code snippets and documents.

Uses sentence-transformers to generate dense vector embeddings
for semantic search over code and documentation.
Default model: BAAI/bge-m3 (multilingual + code, 568M params, 8192 context, 1024 dim).

Supports two backends:
  - "onnx"  (default): onnxruntime + transformers tokenizer — no PyTorch
  - "torch": sentence-transformers + PyTorch — supports MPS/CUDA
"""

from __future__ import annotations

import asyncio
import gc
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import numpy as np

from core.config import EmbeddingConfig
from core.log import get_logger

from .embedding_text_format import (
    MAX_CODE_SNIPPET_CHARS,
    _format_code_text,
    _format_doc_text,
    _smart_truncate,
    doc_dict_for_embedding,
)

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

QUERY_EMBEDDING_CACHE_SIZE = 256


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
    def is_loaded(self) -> bool: ...

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

    def is_loaded(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    def _resolve_onnx_path(self) -> str:
        """Locate or download the ONNX model file.

        Handles repos where ONNX files live in an ``onnx/`` subdirectory
        (e.g. BAAI/bge-m3) as well as repos with a top-level ``model.onnx``.
        For models with external data files (``model.onnx_data``), both files
        are downloaded so ONNX Runtime can resolve the relative reference.
        """
        from pathlib import Path

        from huggingface_hub import hf_hub_download, try_to_load_from_cache

        onnx_repo = self._config.model_name

        candidates = [
            ("onnx/model.onnx", "onnx/model.onnx_data"),
            ("model.onnx", "model.onnx_data"),
        ]

        for onnx_file, data_file in candidates:
            cached = try_to_load_from_cache(onnx_repo, onnx_file)
            if isinstance(cached, str) and Path(cached).is_file():
                return cached

            try:
                path = hf_hub_download(onnx_repo, onnx_file)
                try:
                    hf_hub_download(onnx_repo, data_file)
                except Exception:
                    log.debug("optional_onnx_data_download_failed", repo=onnx_repo, file=data_file, exc_info=True)
                return path
            except Exception:
                continue

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
        if device in ("auto", "mps", "coreml") and "CoreMLExecutionProvider" in available:
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


class _HttpBackend(_EmbeddingBackend):
    """HTTP backend calling an OpenAI-compatible /v1/embeddings endpoint."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._client: Any | None = None

    def load(self) -> None:
        if self._client is not None:
            return

        import httpx

        self._client = httpx.Client(
            base_url=self._config.http_base_url,
            headers=self._build_headers(),
            timeout=self._config.http_timeout,
        )
        log.info(
            "http_backend_loaded",
            base_url=self._config.http_base_url,
            model=self._config.http_model,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.http_api_key:
            headers["Authorization"] = f"Bearer {self._config.http_api_key}"
        return headers

    def is_loaded(self) -> bool:
        return self._client is not None

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        self.load()
        assert self._client is not None

        all_embeddings: list[np.ndarray] = []

        for chunk in _iter_chunks(texts, batch_size):
            embeddings = self._request_with_retry(chunk)
            all_embeddings.append(embeddings)

        return np.vstack(all_embeddings) if all_embeddings else np.empty((0, self._config.dimension))

    def _request_with_retry(self, texts: list[str]) -> np.ndarray:
        import httpx

        max_retries = self._config.http_max_retries
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                resp = self._client.post(
                    "/embeddings",
                    json={
                        "model": self._config.http_model,
                        "input": texts,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                sorted_data = sorted(data["data"], key=lambda x: x["index"])
                embeddings = np.array(
                    [item["embedding"] for item in sorted_data], dtype=np.float32
                )
                return embeddings
            except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as exc:
                last_exc = exc
                log.warning(
                    "http_backend_request_failed",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(exc),
                )

        raise RuntimeError(
            f"HTTP embedding request failed after {max_retries} retries: {last_exc}"
        ) from last_exc

    def unload(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            log.info("http_backend_unloaded")


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
        if self._config.use_fp16 and device == "cuda":
            self._model.half()
            log.info("torch_backend_using_fp16", device=device)
        elif self._config.use_fp16 and device == "mps":
            log.info(
                "torch_backend_skipping_fp16_mps",
                reason="MPS has limited fp16 support, using fp32 for stability",
            )
        log.info("torch_backend_loaded", dimension=self._config.dimension, device=device)

    def is_loaded(self) -> bool:
        return self._model is not None

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

    _shared_instance: EmbeddingGenerator | None = None

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._backend: _EmbeddingBackend | None = None
        self._query_embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._query_embedding_lock = threading.Lock()
        self._encode_lock: asyncio.Lock | None = None

    def _get_encode_lock(self) -> asyncio.Lock:
        if self._encode_lock is None:
            self._encode_lock = asyncio.Lock()
        return self._encode_lock

    @classmethod
    def shared(cls, config: EmbeddingConfig) -> EmbeddingGenerator:
        """Return a singleton instance to avoid loading the model multiple times."""
        if cls._shared_instance is None:
            cls._shared_instance = cls(config)
        return cls._shared_instance

    def _get_backend(self) -> _EmbeddingBackend:
        if self._backend is None:
            effective_backend = self._config.resolve_backend()
            if effective_backend == "http":
                self._backend = _HttpBackend(self._config)
            elif effective_backend == "onnx":
                self._backend = _OnnxBackend(self._config)
            else:
                self._backend = _TorchBackend(self._config)
            log.info(
                "embedding_backend_selected",
                backend=effective_backend,
                device=self._config.resolve_device() if effective_backend != "http" else "remote",
            )
        return self._backend

    def ensure_model_loaded(self) -> None:
        """Load the embedding backend synchronously (for startup warmup and readiness checks)."""
        self._get_backend().load()

    def is_model_loaded(self) -> bool:
        """True once the backend has finished loading weights."""
        if self._backend is None:
            return False
        return self._backend.is_loaded()

    def unload_model(self) -> None:
        """Explicitly release model memory."""
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    async def generate(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        async with self._get_encode_lock():
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
        if not texts:
            return []

        resolved: list[list[float] | None] = [None] * len(texts)
        miss_idx: list[int] = []

        with self._query_embedding_lock:
            for i, t in enumerate(texts):
                if t in self._query_embedding_cache:
                    self._query_embedding_cache.move_to_end(t)
                    resolved[i] = self._query_embedding_cache[t]
                else:
                    miss_idx.append(i)

        if not miss_idx:
            return [resolved[i] for i in range(len(texts))]

        unique_texts: list[str] = []
        seen: set[str] = set()
        for i in miss_idx:
            t = texts[i]
            if t not in seen:
                seen.add(t)
                unique_texts.append(t)

        computed_lists = await self.generate(unique_texts, is_query=True)
        emb_by_text = dict(zip(unique_texts, computed_lists, strict=True))

        with self._query_embedding_lock:
            for t, emb in emb_by_text.items():
                self._query_embedding_cache[t] = emb
                self._query_embedding_cache.move_to_end(t)
                while len(self._query_embedding_cache) > QUERY_EMBEDDING_CACHE_SIZE:
                    self._query_embedding_cache.popitem(last=False)

            for i in miss_idx:
                resolved[i] = self._query_embedding_cache[texts[i]]

        return [resolved[i] for i in range(len(texts))]

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
                item.get("business_summary", ""),
            )
            for item in items
        ]
        return await self.generate(texts, is_query=False)

    async def generate_for_docs(
        self,
        items: list[dict[str, str]],
    ) -> list[list[float]]:
        """Generate embeddings for documentation chunks (markdown sections)."""
        texts = [
            _format_doc_text(
                item.get("title", ""),
                item.get("section", ""),
                item.get("content", ""),
                item.get("heading_context", ""),
            )
            for item in items
        ]
        return await self.generate(texts, is_query=False)

    @property
    def dimension(self) -> int:
        return self._config.dimension
