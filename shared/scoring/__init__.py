"""Multi-axis scoring, bucket classification, and thesis generation (Sprint 9)."""
from .axes import AxisScores, compute_axes
from .buckets import BUCKETS, BUCKET_LABELS, bucket_label, classify_bucket, is_alertable
from .red_flags import CRITICAL_RED_FLAGS, SHARED_RED_FLAGS, detect_red_flags
from .thesis import Thesis, build_thesis

__all__ = [
    "AxisScores", "compute_axes",
    "BUCKETS", "BUCKET_LABELS", "bucket_label", "classify_bucket", "is_alertable",
    "CRITICAL_RED_FLAGS", "SHARED_RED_FLAGS", "detect_red_flags",
    "Thesis", "build_thesis",
]
