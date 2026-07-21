"""
Build data inventory and scene-aware train/val/test splits.

Splits by (dataset, scene/camera) groups to avoid near-duplicate leakage,
as specified in the research proposal.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from src.utils import PROJECT_ROOT, ensure_dirs, load_config, save_json, set_seed

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def _label_from_parts(parts: list[str]) -> int | None:
    lowered = [p.lower() for p in parts]
    occupied_tokens = {"occupied", "busy", "taken", "full", "1"}
    empty_tokens = {"empty", "free", "vacant", "0"}
    for p in reversed(lowered):
        if p in occupied_tokens:
            return 1
        if p in empty_tokens:
            return 0
    return None


def _weather_from_parts(parts: list[str]) -> str | None:
    for p in parts:
        pl = p.lower()
        if pl in {"sunny", "cloudy", "rainy", "overcast", "rain", "clear"}:
            return "rainy" if pl == "rain" else ("cloudy" if pl == "overcast" else pl)
    return None


def scan_raw(raw: Path) -> list[dict]:
    rows: list[dict] = []
    for img in raw.rglob("*"):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = img.relative_to(PROJECT_ROOT)
        parts = list(img.relative_to(raw).parts)
        label = _label_from_parts(parts)
        if label is None:
            continue
        dataset = "unknown"
        if any("pklot" in p.lower() for p in parts):
            dataset = "pklot"
        elif any("cnr" in p.lower() for p in parts):
            dataset = "cnrpark_ext"

        # Heuristic scene/camera: first folder after dataset root that is not weather/label
        scene = "unknown"
        camera = "unknown"
        for p in parts:
            pl = p.lower()
            if pl in {
                "pklot",
                "pklotsegmented",
                "cnrpark-ext",
                "cnr-ext",
                "patches",
                "sunny",
                "cloudy",
                "rainy",
                "empty",
                "occupied",
                "free",
                "busy",
                "raw",
            }:
                continue
            if p.lower().endswith((".jpg", ".png", ".jpeg", ".bmp")):
                continue
            scene = p
            camera = p
            break

        rows.append(
            {
                "path": str(rel).replace("\\", "/"),
                "label": int(label),
                "label_name": "occupied" if label == 1 else "empty",
                "dataset": dataset,
                "scene": scene,
                "camera": camera,
                "weather": _weather_from_parts(parts) or "unknown",
            }
        )
    return rows


def _image_level_split(
    df: pd.DataFrame,
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> pd.DataFrame:
    """Stratified per-image split used when there are too few scenes."""
    strat = df["label"] if df["label"].nunique() > 1 else None
    train_df, temp_df = train_test_split(
        df, test_size=(1 - train_ratio), stratify=strat, random_state=seed
    )
    relative_val = val_ratio / (val_ratio + (1 - train_ratio - val_ratio))
    strat_temp = temp_df["label"] if temp_df["label"].nunique() > 1 else None
    val_df, test_df = train_test_split(
        temp_df, test_size=(1 - relative_val), stratify=strat_temp, random_state=seed
    )
    train_df, val_df, test_df = train_df.copy(), val_df.copy(), test_df.copy()
    train_df["split"] = "train"
    val_df["split"] = "val"
    test_df["split"] = "test"
    return pd.concat([train_df, val_df, test_df], ignore_index=True)


def scene_aware_split(
    df: pd.DataFrame,
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> pd.DataFrame:
    """Assign splits by grouping on (dataset, scene) to reduce frame leakage."""
    df = df.copy()
    df["group"] = df["dataset"].astype(str) + "::" + df["scene"].astype(str)
    groups = df["group"].unique().tolist()
    # Need >= 4 scene-groups to safely fill train/val/test without empty folds
    if len(groups) < 4:
        out = _image_level_split(df.drop(columns=["group"]), train_ratio, val_ratio, seed)
        return out

    group_label = df.groupby("group")["label"].mean().round().astype(int)
    group_df = group_label.reset_index(name="maj_label")
    try:
        strat = group_df["maj_label"] if group_df["maj_label"].nunique() > 1 else None
        g_train, g_temp = train_test_split(
            group_df,
            test_size=(1 - train_ratio),
            stratify=strat,
            random_state=seed,
        )
        if len(g_temp) < 2:
            return _image_level_split(df.drop(columns=["group"]), train_ratio, val_ratio, seed)
        relative_val = val_ratio / (val_ratio + (1 - train_ratio - val_ratio))
        strat_temp = g_temp["maj_label"] if g_temp["maj_label"].nunique() > 1 else None
        g_val, g_test = train_test_split(
            g_temp,
            test_size=(1 - relative_val),
            stratify=strat_temp,
            random_state=seed,
        )
    except ValueError:
        return _image_level_split(df.drop(columns=["group"]), train_ratio, val_ratio, seed)

    mapping = {}
    for g in g_train["group"]:
        mapping[g] = "train"
    for g in g_val["group"]:
        mapping[g] = "val"
    for g in g_test["group"]:
        mapping[g] = "test"
    df["split"] = df["group"].map(mapping)
    return df.drop(columns=["group"])


def prepare(use_existing_inventory: Path | None = None) -> Path:
    cfg = load_config()
    set_seed(cfg["seed"])
    paths = ensure_dirs(cfg)

    if use_existing_inventory and use_existing_inventory.exists():
        inv = pd.read_json(use_existing_inventory)
        rows = inv.to_dict(orient="records")
    else:
        demo_inv = paths["processed"] / "data_inventory_demo.json"
        if demo_inv.exists() and not any(paths["raw"].rglob("*.jpg")):
            rows = pd.read_json(demo_inv).to_dict(orient="records")
        else:
            rows = scan_raw(paths["raw"])
            if not rows and demo_inv.exists():
                rows = pd.read_json(demo_inv).to_dict(orient="records")

    if not rows:
        raise SystemExit(
            "No labeled images found. Run: python -m src.download_datasets --demo\n"
            "Or place PKLot / CNRPark-EXT under data/raw/"
        )

    df = pd.DataFrame(rows)
    # Drop corrupt/unreadable later during training; exclude unlabeled already done
    before = len(df)
    df = df.dropna(subset=["label"]).drop_duplicates(subset=["path"])
    excluded = before - len(df)

    df = scene_aware_split(df, cfg["train_ratio"], cfg["val_ratio"], cfg["seed"])

    inv_path = paths["processed"] / "data_inventory.json"
    split_path = paths["processed"] / "split_manifest.csv"
    summary_path = paths["processed"] / "prepare_summary.json"

    df.to_json(inv_path, orient="records", indent=2)
    df.to_csv(split_path, index=False)
    save_json(
        {
            "n_images": int(len(df)),
            "excluded_duplicates": int(excluded),
            "by_split": df["split"].value_counts().to_dict(),
            "by_label": df["label_name"].value_counts().to_dict(),
            "by_dataset": df["dataset"].value_counts().to_dict(),
            "by_weather": df["weather"].value_counts().to_dict(),
            "seed": cfg["seed"],
        },
        summary_path,
    )
    print(f"Inventory: {inv_path} ({len(df)} images)")
    print(f"Split manifest: {split_path}")
    print(df.groupby(["split", "label_name"]).size())
    return split_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=str, default=None)
    args = parser.parse_args()
    inv = Path(args.inventory) if args.inventory else None
    prepare(inv)


if __name__ == "__main__":
    main()
