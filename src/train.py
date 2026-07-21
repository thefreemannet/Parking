"""Train classification models on the prepared split manifest."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from PIL import Image
from tensorflow import keras

from src.models import build_model, get_preprocess_fn, get_train_augmenter
from src.utils import PROJECT_ROOT, ensure_dirs, load_config, save_json, set_seed


def _load_split(paths) -> pd.DataFrame:
    split_path = paths["processed"] / "split_manifest.csv"
    if not split_path.exists():
        raise SystemExit("Missing split_manifest.csv — run: python -m src.prepare_data")
    return pd.read_csv(split_path)


def _read_image_uint8(path: str, image_size: tuple[int, int]) -> np.ndarray:
    """PIL loader — works on Windows UNC shares where tf.io.read_file often fails."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im = im.resize((image_size[1], image_size[0]), Image.BILINEAR)
        return np.asarray(im, dtype=np.float32)


def make_dataset(
    df: pd.DataFrame,
    image_size: tuple[int, int],
    batch_size: int,
    shuffle: bool,
    augmenter: keras.Sequential | None = None,
    preprocess_fn=None,
    seed: int = 42,
) -> tf.data.Dataset:
    abs_paths = [str((PROJECT_ROOT / p).resolve()) for p in df["path"].tolist()]
    labels = np.asarray(df["label"].astype(np.float32).tolist(), dtype=np.float32)

    def gen():
        for path, label in zip(abs_paths, labels):
            yield _read_image_uint8(path, image_size), label

    out_sig = (
        tf.TensorSpec(shape=(*image_size, 3), dtype=tf.float32),
        tf.TensorSpec(shape=(), dtype=tf.float32),
    )
    ds = tf.data.Dataset.from_generator(gen, output_signature=out_sig)
    # from_generator loses cardinality; set it for steps estimates
    ds = ds.apply(tf.data.experimental.assert_cardinality(len(abs_paths)))

    if shuffle:
        ds = ds.shuffle(buffer_size=min(len(abs_paths), 2048), seed=seed, reshuffle_each_iteration=True)

    if augmenter is not None:
        ds = ds.map(lambda x, y: (augmenter(x, training=True), y), num_parallel_calls=tf.data.AUTOTUNE)

    if preprocess_fn is not None:
        ds = ds.map(lambda x, y: (preprocess_fn(x), y), num_parallel_calls=tf.data.AUTOTUNE)

    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def train_one(model_name: str, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    set_seed(cfg["seed"])
    paths = ensure_dirs(cfg)
    df = _load_split(paths)
    image_size = tuple(cfg["image_size"])
    bs = cfg["batch_size"]

    train_df = df[df["split"] == "train"]
    val_df = df[df["split"] == "val"]
    if train_df.empty or val_df.empty:
        raise SystemExit("Train/val splits are empty. Re-run prepare_data.")

    augmenter = get_train_augmenter(cfg)
    preprocess_fn = get_preprocess_fn(model_name)
    train_ds = make_dataset(
        train_df,
        image_size,
        bs,
        shuffle=True,
        augmenter=augmenter,
        preprocess_fn=preprocess_fn,
        seed=cfg["seed"],
    )
    val_ds = make_dataset(
        val_df, image_size, bs, shuffle=False, preprocess_fn=preprocess_fn
    )

    model = build_model(model_name, image_size, cfg["learning_rate"])
    ckpt = paths["models"] / f"{model_name}_best.keras"
    callbacks = [
        keras.callbacks.ModelCheckpoint(
            filepath=str(ckpt), monitor="val_accuracy", save_best_only=True, mode="max"
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=cfg["early_stopping_patience"],
            restore_best_weights=True,
        ),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=2, min_lr=1e-6),
    ]

    t0 = time.perf_counter()
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=cfg["epochs"],
        callbacks=callbacks,
        verbose=1,
    )
    elapsed = time.perf_counter() - t0
    model.save(ckpt)

    hist = {k: [float(x) for x in v] for k, v in history.history.items()}
    meta = {
        "model": model_name,
        "checkpoint": str(ckpt.relative_to(PROJECT_ROOT)),
        "train_seconds": elapsed,
        "epochs_ran": len(hist.get("loss", [])),
        "best_val_accuracy": max(hist.get("val_accuracy", [0.0])),
        "n_train": int(len(train_df)),
        "n_val": int(len(val_df)),
        "history": hist,
    }
    save_json(meta, paths["metrics"] / f"{model_name}_train_meta.json")
    print(f"Saved {ckpt}")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        default="all",
        help="baseline|mobilenetv3|vgg16|resnet50|all",
    )
    parser.add_argument("--epochs", type=int, default=None)
    args = parser.parse_args()
    cfg = load_config()
    if args.epochs is not None:
        cfg["epochs"] = args.epochs

    names = cfg["models"] if args.model == "all" else [args.model]
    for name in names:
        print(f"\n=== Training {name} ===")
        train_one(name, cfg)


if __name__ == "__main__":
    main()
