#!/usr/bin/env python3
"""
Lazy-loaded HuggingFace Intent Classifier for user prompts.

Uses zero-shot classification to categorize user requests into intents.
Model loads on first use (~3s), subsequent calls ~30-50ms.

Intents:
  - code_review: Review code, find issues, audit
  - debug: Fix bugs, investigate errors, troubleshoot
  - implement: Build new features, add functionality
  - refactor: Restructure, clean up, improve code
  - explain: Understand code, documentation, how things work
  - research: Search, find information, explore options
  - configure: Setup, install, environment changes
  - test: Write tests, run tests, verify behavior
"""

from __future__ import annotations

import os
import time
from typing import Optional

# Lazy-loaded model
_CLASSIFIER = None
_CLASSIFIER_LOAD_TIME: float = 0.0
_CLASSIFIER_LOADING = False  # True while background load in progress
_MODEL_NAME = "facebook/bart-large-mnli"  # Good balance of speed/accuracy

# Intent labels
INTENT_LABELS = [
    "code_review",
    "debug",
    "implement",
    "refactor",
    "explain",
    "research",
    "configure",
    "test",
]

# Intent to context mapping - what each intent should trigger
INTENT_CONTEXT = {
    "code_review": {
        "hooks": ["audit", "void"],
        "message": "🔍 CODE REVIEW MODE: Consider /audit and /void for systematic analysis",
    },
    "debug": {
        "hooks": ["thinkdeep", "debug"],
        "message": "🐛 DEBUG MODE: Use systematic hypothesis testing. Consider PAL debug tool.",
    },
    "implement": {
        "hooks": ["bead_check"],
        "message": "🔨 IMPLEMENT MODE: Track with beads. Check for existing solutions first.",
    },
    "refactor": {
        "hooks": ["drift", "audit"],
        "message": "♻️ REFACTOR MODE: Verify no behavior changes. Run tests after.",
    },
    "explain": {
        "hooks": [],
        "message": None,  # No special context needed
    },
    "research": {
        "hooks": ["websearch", "memory"],
        "message": "🔬 RESEARCH MODE: Check memory first, then web. Cite sources.",
    },
    "configure": {
        "hooks": ["inventory", "sysinfo"],
        "message": "⚙️ CONFIG MODE: Verify environment with /inventory and /sysinfo",
    },
    "test": {
        "hooks": [],
        "message": "🧪 TEST MODE: Prefer pytest. Run existing tests before writing new ones.",
    },
}


def _load_classifier():
    """Load the classifier model. Called once per session."""
    global _CLASSIFIER, _CLASSIFIER_LOAD_TIME

    if _CLASSIFIER is not None:
        return _CLASSIFIER

    start = time.time()
    try:
        from transformers import pipeline

        # Use CPU, disable progress bars for cleaner output
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

        _CLASSIFIER = pipeline(
            "zero-shot-classification",
            model=_MODEL_NAME,
            device=-1,  # CPU
        )
        _CLASSIFIER_LOAD_TIME = time.time() - start
        return _CLASSIFIER
    except ImportError:
        # transformers not installed
        return None
    except Exception:
        # Model load failed
        return None


def is_ready() -> bool:
    """Check if the classifier is loaded and ready (non-blocking)."""
    return _CLASSIFIER is not None


def classify_intent(prompt: str, threshold: float = 0.3) -> Optional[dict]:
    """
    Classify user prompt into an intent category (non-blocking).

    If model isn't loaded yet, starts background loading and returns None.
    Subsequent calls will work once model is ready.

    Args:
        prompt: User's prompt text
        threshold: Minimum confidence score (0-1) to return an intent

    Returns:
        Dict with 'intent', 'confidence', 'context' or None if not ready/below threshold
    """
    global _CLASSIFIER_LOADING

    # Skip very short prompts
    if len(prompt.strip()) < 10:
        return None

    # Non-blocking: if model not loaded, start background load and return
    if _CLASSIFIER is None:
        if not _CLASSIFIER_LOADING:
            prewarm()  # Start background loading
        return None  # Not ready yet, skip this prompt

    classifier = _CLASSIFIER

    try:
        # Truncate very long prompts for efficiency
        text = prompt[:1000] if len(prompt) > 1000 else prompt

        result = classifier(text, INTENT_LABELS, multi_label=False)

        top_intent = result["labels"][0]
        top_score = result["scores"][0]

        if top_score < threshold:
            return None

        context = INTENT_CONTEXT.get(top_intent, {})

        return {
            "intent": top_intent,
            "confidence": top_score,
            "message": context.get("message"),
            "hooks": context.get("hooks", []),
        }
    except Exception:
        return None


def get_model_status() -> dict:
    """Get status of the intent classifier model."""
    return {
        "loaded": _CLASSIFIER is not None,
        "model": _MODEL_NAME,
        "load_time_seconds": _CLASSIFIER_LOAD_TIME,
    }


def prewarm():
    """Pre-load the model in a background thread (non-blocking)."""
    global _CLASSIFIER_LOADING
    import threading

    if _CLASSIFIER is not None or _CLASSIFIER_LOADING:
        return  # Already loaded or loading

    _CLASSIFIER_LOADING = True

    def _load_and_mark():
        global _CLASSIFIER_LOADING
        try:
            _load_classifier()
        finally:
            _CLASSIFIER_LOADING = False

    thread = threading.Thread(target=_load_and_mark, daemon=True)
    thread.start()
