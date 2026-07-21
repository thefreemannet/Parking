"""
Evaluate trained classifiers on the held-out test set.

Reports accuracy, precision, recall, F1, confusion matrices, inference time,
model size, and condition-level breakdowns (weather / dataset) when available.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import tensorflow as tf
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from tensorflow import keras

from src.models import get_preprocess_fn
from src.train import make_dataset
from src.utils import PROJECT_ROOT, ensure_dirs, load_config, save_json, set_seed


def _bootstrap_ci(y_true, y_pred, metric_fn, n_boot: int = 500, seed: int = 42):
    rng = np.random.default_rng(seed)
    vals = []
    n = len(y_true)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        vals.append(float(metric_fn(y_true[idx], y_pred[idx])))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def measure_inference(model, sample_batch, warmup: int = 5, runs: int = 30) -> dict:
    # warmup
    for _ in range(warmup):
        _ = model(sample_batch, training=False)
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        _ = model(sample_batch, training=False)
        times.append(time.perf_counter() - t0)
    arr = np.array(times)
    bs = int(sample_batch.shape[0])
    mean_batch = float(arr.mean())
    return {
        "batch_size": bs,
        "mean_batch_seconds": mean_batch,
        "mean_image_ms": mean_batch * 1000.0 / bs,
        "fps": bs / mean_batch if mean_batch > 0 else 0.0,
    }


def evaluate_model(model_name: str, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    set_seed(cfg["seed"])
    paths = ensure_dirs(cfg)
    df = pd.read_csv(paths["processed"] / "split_manifest.csv")
    test_df = df[df["split"] == "test"].reset_index(drop=True)
    if test_df.empty:
        raise SystemExit("Test split empty.")

    ckpt = paths["models"] / f"{model_name}_best.keras"
    if not ckpt.exists():
        raise SystemExit(f"Missing checkpoint: {ckpt}. Train first.")

    model = keras.models.load_model(ckpt, compile=False)
    image_size = tuple(cfg["image_size"])
    bs = cfg["batch_size"]
    preprocess_fn = get_preprocess_fn(model_name)
    test_ds = make_dataset(
        test_df, image_size, bs, shuffle=False, preprocess_fn=preprocess_fn
    )

    probs = model.predict(test_ds, verbose=0).reshape(-1)
    # Align length if last batch padding somehow differs
    n = len(test_df)
    probs = probs[:n]
    y_true = test_df["label"].to_numpy()
    y_pred = (probs >= 0.5).astype(int)

    metrics = {
        "model": model_name,
        "n_test": int(n),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, target_names=["empty", "occupied"], output_dict=True, zero_division=0
        ),
    }
    metrics["accuracy_ci95"] = _bootstrap_ci(y_true, y_pred, accuracy_score, seed=cfg["seed"])
    metrics["f1_ci95"] = _bootstrap_ci(
        y_true, y_pred, lambda a, b: f1_score(a, b, zero_division=0), seed=cfg["seed"]
    )

    # model size
    metrics["model_size_mb"] = round(ckpt.stat().st_size / (1024 * 1024), 3)

    # inference timing
    for xb, _ in test_ds.take(1):
        metrics["inference"] = measure_inference(model, xb)
        break

    # condition-level
    test_df = test_df.copy()
    test_df["y_pred"] = y_pred
    test_df["prob"] = probs
    by_condition = {}
    for key in ("weather", "dataset", "camera"):
        if key not in test_df.columns:
            continue
        block = {}
        for val, g in test_df.groupby(key):
            if len(g) < 5:
                continue
            yt, yp = g["label"].to_numpy(), g["y_pred"].to_numpy()
            block[str(val)] = {
                "n": int(len(g)),
                "accuracy": float(accuracy_score(yt, yp)),
                "f1": float(f1_score(yt, yp, zero_division=0)),
            }
        by_condition[key] = block
    metrics["by_condition"] = by_condition

    # confusion matrix figure
    cm = np.array(metrics["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(4.5, 4))
    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=["empty", "occupied"],
        yticklabels=["empty", "occupied"],
        ax=ax,
    )
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(f"{model_name} — Test Confusion Matrix")
    fig_path = paths["figures"] / f"{model_name}_confusion_matrix.png"
    fig.tight_layout()
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)

    # failure cases CSV (for qualitative review)
    fails = test_df[test_df["label"] != test_df["y_pred"]].copy()
    fails.to_csv(paths["metrics"] / f"{model_name}_failures.csv", index=False)

    out = paths["metrics"] / f"{model_name}_test_metrics.json"
    save_json(metrics, out)
    print(f"{model_name}: acc={metrics['accuracy']:.3f} f1={metrics['f1']:.3f} -> {out}")
    return metrics


def summarize_all(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    paths = ensure_dirs(cfg)
    rows = []
    for name in cfg["models"]:
        p = paths["metrics"] / f"{name}_test_metrics.json"
        if not p.exists():
            continue
        m = pd.read_json(p, typ="series")
        # pd.read_json on object dict is awkward; use json
        import json

        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        rows.append(
            {
                "model": m["model"],
                "accuracy": m["accuracy"],
                "precision": m["precision"],
                "recall": m["recall"],
                "f1": m["f1"],
                "macro_f1": m["macro_f1"],
                "model_size_mb": m["model_size_mb"],
                "mean_image_ms": m.get("inference", {}).get("mean_image_ms"),
                "fps": m.get("inference", {}).get("fps"),
            }
        )
    summary = pd.DataFrame(rows)
    out = paths["metrics"] / "classification_summary.csv"
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f"Wrote {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="all")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    if args.summary_only:
        summarize_all(cfg)
        return
    names = cfg["models"] if args.model == "all" else [args.model]
    for name in names:
        print(f"\n=== Evaluating {name} ===")
        evaluate_model(name, cfg)
    summarize_all(cfg)


if __name__ == "__main__":
    main()
