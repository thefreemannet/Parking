"""Package marker — import helpers from src.utils.

Env vars below must be set before TensorFlow/scikit-learn load their native
libraries; importing anything from `src` guarantees that ordering.
"""
import os
import sys

# macOS: TensorFlow and scikit-learn each bundle their own OpenMP runtime;
# loading both aborts the process (SIGABRT) during evaluation unless allowed.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")

# Headless-safe plotting (figures are only saved to files, never shown).
os.environ.setdefault("MPLBACKEND", "Agg")
