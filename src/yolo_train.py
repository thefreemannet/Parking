"""Optional YOLO full-scene detection track (YOLOv8s / YOLO11n).

Requires full-scene annotations in YOLO format under data/processed/yolo/.
Disabled by default in configs/default.yaml (yolo.enabled: false).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.utils import PROJECT_ROOT, ensure_dirs, load_config, save_json


def run_yolo(model_name: str = "yolov8s") -> dict:
    cfg = load_config()
    paths = ensure_dirs(cfg)
    data_yaml = paths["processed"] / "yolo" / "data.yaml"
    if not data_yaml.exists():
        raise SystemExit(
            f"Missing {data_yaml}. Prepare YOLO labels (images + labels + data.yaml) "
            "before enabling the detection track."
        )
    from ultralytics import YOLO

    weights = "yolo11n.pt" if "11" in model_name.lower() else "yolov8s.pt"
    model = YOLO(weights)
    results = model.train(
        data=str(data_yaml),
        epochs=cfg.get("yolo", {}).get("epochs", 50),
        imgsz=cfg.get("yolo", {}).get("imgsz", 640),
        project=str(paths["outputs"] / "yolo"),
        name=model_name,
        seed=cfg["seed"],
        exist_ok=True,
    )
    meta = {"model": model_name, "weights": weights, "data": str(data_yaml)}
    save_json(meta, paths["metrics"] / f"{model_name}_train_meta.json")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="yolov8s", choices=["yolov8s", "yolo11n"])
    args = parser.parse_args()
    cfg = load_config()
    if not cfg.get("yolo", {}).get("enabled", False):
        print("YOLO track disabled in configs/default.yaml (set yolo.enabled: true to run).")
        return
    run_yolo(args.model)


if __name__ == "__main__":
    main()
