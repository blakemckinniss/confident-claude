"""Analysis module for code quality checks."""

from .god_component_detector import (
    detect_god_component,
    analyze_complexity,
    format_detection_message,
    ComplexityMetrics,
    DetectionResult,
    LINE_THRESHOLD_WARN,
    LINE_THRESHOLD_BLOCK,
)

__all__ = [
    "detect_god_component",
    "analyze_complexity",
    "format_detection_message",
    "ComplexityMetrics",
    "DetectionResult",
    "LINE_THRESHOLD_WARN",
    "LINE_THRESHOLD_BLOCK",
]
