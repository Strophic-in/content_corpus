"""Sentence embeddings on the CPU, free: bge-small-en-v1.5 (quantised ONNX, ~34 MB).

Used to tell whether a new idea is really new — the same subject in other words
scores high. Runs with what the worker already has (onnxruntime, tokenizers,
huggingface_hub); the model downloads once into the Hugging Face cache.
"""

from __future__ import annotations

import functools

import numpy as np

REPO = "Xenova/bge-small-en-v1.5"
DIM = 384


@functools.lru_cache(maxsize=1)
def _model():
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(hf_hub_download(REPO, "tokenizer.json"))
    tok.enable_truncation(max_length=256)
    tok.enable_padding()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    sess = ort.InferenceSession(hf_hub_download(REPO, "onnx/model_quantized.onnx"), opts,
                                providers=["CPUExecutionProvider"])
    return tok, sess, {i.name for i in sess.get_inputs()}


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised vectors, shape (len(texts), 384): cosine similarity = dot product."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    tok, sess, names = _model()
    enc = tok.encode_batch(texts)
    feeds = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
             "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
             "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64)}
    hidden = sess.run(None, {k: v for k, v in feeds.items() if k in names})[0]
    cls = hidden[:, 0, :]                                    # bge pools on the [CLS] token
    return (cls / np.linalg.norm(cls, axis=1, keepdims=True)).astype(np.float32)
