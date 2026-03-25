#!/usr/bin/env python3
"""Export a sentence-transformers model to ONNX format.

Usage:
    uv pip install torch sentence-transformers   # one-time only
    uv run scripts/export_onnx.py [--model nomic-ai/CodeRankEmbed] [--output models/]

After export you can uninstall torch:
    uv pip uninstall torch sentence-transformers

Then point the service to the ONNX file:
    EMBEDDING__ONNX_PATH=models/model.onnx
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export embedding model to ONNX")
    parser.add_argument("--model", default="nomic-ai/CodeRankEmbed", help="HuggingFace model name")
    parser.add_argument("--output", default="models", help="Output directory")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version")
    args = parser.parse_args()

    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "model.onnx"

    print(f"Loading model: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    st_model = SentenceTransformer(args.model, device="cpu", trust_remote_code=True)

    hf_model = st_model[0].auto_model
    hf_model.eval()

    dummy = tokenizer("dummy", return_tensors="pt", padding="max_length", max_length=32, truncation=True)

    print(f"Exporting to: {onnx_path}")
    torch.onnx.export(
        hf_model,
        (dummy["input_ids"], dummy["attention_mask"]),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "last_hidden_state": {0: "batch", 1: "seq"},
        },
        opset_version=args.opset,
    )

    tokenizer.save_pretrained(str(output_dir))

    size_mb = onnx_path.stat().st_size / (1024 * 1024)
    print(f"Done! ONNX model: {onnx_path} ({size_mb:.1f} MB)")
    print(f"Set EMBEDDING__ONNX_PATH={onnx_path} in your .env")


if __name__ == "__main__":
    main()
