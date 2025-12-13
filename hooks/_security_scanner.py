#!/usr/bin/env python3
"""
Lazy-loaded CodeBERT Security Scanner for code changes.

Uses mrm8488/codebert-base-finetuned-detect-insecure-code to detect
potential security vulnerabilities in code (resource leaks, use-after-free,
DoS vectors).

Model loads on first use (~5-10s), subsequent calls ~100-200ms.
Non-blocking: returns None while loading, scans once ready.

Accuracy: ~65% - use as advisory warning, not hard block.
"""

from __future__ import annotations

import os
import time
from typing import Optional

# Lazy-loaded model
_MODEL = None
_TOKENIZER = None
_LOAD_TIME: float = 0.0
_LOADING = False
_MODEL_NAME = "mrm8488/codebert-base-finetuned-detect-insecure-code"


def _load_model():
    """Load the CodeBERT model. Called once per session."""
    global _MODEL, _TOKENIZER, _LOAD_TIME

    if _MODEL is not None:
        return _MODEL, _TOKENIZER

    start = time.time()
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

        _TOKENIZER = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _MODEL = AutoModelForSequenceClassification.from_pretrained(_MODEL_NAME)
        _LOAD_TIME = time.time() - start
        return _MODEL, _TOKENIZER
    except ImportError:
        return None, None
    except Exception:
        return None, None


def is_ready() -> bool:
    """Check if the scanner is loaded and ready (non-blocking)."""
    return _MODEL is not None and _TOKENIZER is not None


def scan_code(code: str, threshold: float = 0.6) -> Optional[dict]:
    """
    Scan code for potential security vulnerabilities (non-blocking).

    If model isn't loaded yet, starts background loading and returns None.

    Args:
        code: Source code to scan
        threshold: Confidence threshold (0-1) to flag as insecure

    Returns:
        Dict with 'is_insecure', 'confidence', 'recommendation' or None if not ready
    """
    global _LOADING

    # Skip very short code
    if not code or len(code.strip()) < 20:
        return None

    # Non-blocking: if model not loaded, start background load
    if _MODEL is None or _TOKENIZER is None:
        if not _LOADING:
            prewarm()
        return None

    try:
        import torch

        # Truncate very long code for efficiency
        code_text = code[:2000] if len(code) > 2000 else code

        inputs = _TOKENIZER(
            code_text,
            return_tensors="pt",
            truncation=True,
            padding="max_length",
            max_length=512,
        )

        with torch.no_grad():
            outputs = _MODEL(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=1)

        # Class 0 = secure, Class 1 = insecure
        insecure_prob = probs[0][1].item()
        is_insecure = insecure_prob >= threshold

        if not is_insecure:
            return None  # Only return results for flagged code

        return {
            "is_insecure": True,
            "confidence": insecure_prob,
            "recommendation": _get_recommendation(insecure_prob),
        }
    except Exception:
        return None


def _get_recommendation(confidence: float) -> str:
    """Get security recommendation based on confidence level."""
    if confidence >= 0.8:
        return "⚠️ HIGH RISK: Review for resource leaks, buffer issues, or injection vectors"
    elif confidence >= 0.7:
        return "⚠️ MEDIUM RISK: Check error handling and input validation"
    else:
        return "⚠️ LOW RISK: Consider defensive coding practices"


def get_model_status() -> dict:
    """Get status of the security scanner model."""
    return {
        "loaded": is_ready(),
        "model": _MODEL_NAME,
        "load_time_seconds": _LOAD_TIME,
        "loading": _LOADING,
    }


def prewarm():
    """Pre-load the model in a background thread (non-blocking)."""
    global _LOADING
    import threading

    if is_ready() or _LOADING:
        return

    _LOADING = True

    def _load_and_mark():
        global _LOADING
        try:
            _load_model()
        finally:
            _LOADING = False

    thread = threading.Thread(target=_load_and_mark, daemon=True)
    thread.start()
