"""
Download / stage PKLot and CNRPark-EXT, or build a local demo subset.

Official sources (manual download if auto-fetch is blocked):
  PKLot:       https://web.inf.ufpr.br/vri/databases/parking-lot-database/
  CNRPark-EXT: http://cnrpark.it/

Usage:
  python -m src.download_datasets --demo          # tiny synthetic set to verify pipeline
  python -m src.download_datasets --check         # inventory existing data/raw
  python -m src.download_datasets --from-zip PATH # unpack a downloaded archive into data/raw
"""
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from src.utils import PROJECT_ROOT, ensure_dirs, load_config, save_json, set_seed


PKLOT_HINT = (
    "PKLot (UFPR): https://web.inf.ufpr.br/vri/databases/parking-lot-database/\n"
    "  Expected layout after extract:\n"
    "    data/raw/PKLot/PKLotSegmented/{PUC|UFPR04|UFPR05}/{Sunny|Cloudy|Rainy}/..."
)
CNR_HINT = (
    "CNRPark-EXT: http://cnrpark.it/\n"
    "  Expected layout after extract:\n"
    "    data/raw/CNRPark-EXT/PATCHES/{free|busy}/...\n"
    "    or data/raw/CNR-EXT/... with occupied/empty style folders"
)


def _make_patch(label: int, weather: str, idx: int, size: int = 128) -> Image.Image:
    """Synthetic occupied (1) / empty (0) patch for pipeline smoke tests."""
    rng = np.random.default_rng(idx + label * 10_000)
    if label == 0:
        base = (40, 45, 50) if weather == "Rainy" else (70, 75, 80)
        img = Image.new("RGB", (size, size), base)
        draw = ImageDraw.Draw(img)
        # parking lines
        draw.rectangle([8, 8, size - 8, size - 8], outline=(220, 220, 200), width=2)
        noise = rng.integers(0, 25, (size, size, 3), dtype=np.uint8)
        arr = np.clip(np.array(img, dtype=np.int16) + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)
    # occupied: asphalt + car-like blob
    base = (30, 32, 35) if weather != "Sunny" else (55, 58, 62)
    img = Image.new("RGB", (size, size), base)
    draw = ImageDraw.Draw(img)
    color = tuple(int(c) for c in rng.integers(20, 200, 3))
    draw.rounded_rectangle([20, 35, size - 20, size - 25], radius=12, fill=color)
    draw.ellipse([28, 42, 48, 58], fill=(180, 200, 220))
    draw.ellipse([size - 48, 42, size - 28, 58], fill=(180, 200, 220))
    if weather == "Rainy":
        for _ in range(40):
            x, y = int(rng.integers(0, size)), int(rng.integers(0, size))
            draw.line([(x, y), (x + 2, y + 6)], fill=(120, 140, 180), width=1)
    return img


def create_demo_dataset(n_per_class: int = 80) -> Path:
    """Create a tiny PKLot-like + CNR-like tree under data/raw for end-to-end runs."""
    cfg = load_config()
    set_seed(cfg["seed"])
    paths = ensure_dirs(cfg)
    raw = paths["raw"]

    weathers = ["Sunny", "Cloudy", "Rainy"]
    cameras = ["PUC", "UFPR04"]
    inventory = []

    for cam in cameras:
        for weather in weathers:
            for label_name, label in (("Empty", 0), ("Occupied", 1)):
                out_dir = raw / "PKLot" / "PKLotSegmented" / cam / weather / label_name
                out_dir.mkdir(parents=True, exist_ok=True)
                for i in range(n_per_class // (len(cameras) * len(weathers))):
                    idx = hash((cam, weather, label_name, i)) % 1_000_000
                    img = _make_patch(label, weather, idx)
                    fname = f"{cam}_{weather}_{label_name}_{i:04d}.jpg"
                    fpath = out_dir / fname
                    img.save(fpath, quality=90)
                    inventory.append(
                        {
                            "path": str(fpath.relative_to(PROJECT_ROOT)),
                            "label": label,
                            "label_name": label_name.lower(),
                            "dataset": "pklot",
                            "scene": cam,
                            "camera": cam,
                            "weather": weather.lower(),
                        }
                    )

    for label_name, label in (("free", 0), ("busy", 1)):
        out_dir = raw / "CNRPark-EXT" / "PATCHES" / label_name
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n_per_class // 2):
            weather = weathers[i % 3]
            idx = hash(("cnr", label_name, i)) % 1_000_000
            img = _make_patch(label, weather, idx)
            fname = f"cnr_{label_name}_{i:04d}.jpg"
            fpath = out_dir / fname
            img.save(fpath, quality=90)
            inventory.append(
                {
                    "path": str(fpath.relative_to(PROJECT_ROOT)),
                    "label": label,
                    "label_name": "empty" if label == 0 else "occupied",
                    "dataset": "cnrpark_ext",
                    "scene": "cnr_cam_a",
                    "camera": "cnr_cam_a",
                    "weather": weather.lower(),
                }
            )

    inv_path = paths["processed"] / "data_inventory_demo.json"
    save_json(inventory, inv_path)
    print(f"Demo dataset ready: {len(inventory)} images")
    print(f"Inventory: {inv_path}")
    return raw


def unpack_zip(zip_path: Path, dest_name: str) -> Path:
    paths = ensure_dirs()
    dest = paths["raw"] / dest_name
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    print(f"Extracted {zip_path} -> {dest}")
    return dest


def check_raw() -> None:
    paths = ensure_dirs()
    raw = paths["raw"]
    print(f"Raw data root: {raw}")
    if not any(raw.iterdir()):
        print("EMPTY. Use --demo or place PKLot / CNRPark-EXT under data/raw/")
        print(PKLOT_HINT)
        print(CNR_HINT)
        return
    for p in sorted(raw.rglob("*")):
        if p.is_dir():
            n_img = sum(1 for x in p.glob("*") if x.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"})
            if n_img:
                print(f"  {p.relative_to(raw)}: {n_img} images")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage parking datasets")
    parser.add_argument("--demo", action="store_true", help="Create synthetic demo patches")
    parser.add_argument("--check", action="store_true", help="List what is under data/raw")
    parser.add_argument("--from-zip", type=str, help="Path to a downloaded .zip archive")
    parser.add_argument("--dest-name", type=str, default="imported", help="Folder name under data/raw")
    parser.add_argument("--demo-n", type=int, default=80, help="Approx patches per class for --demo")
    args = parser.parse_args()

    if args.demo:
        create_demo_dataset(n_per_class=args.demo_n)
    elif args.from_zip:
        unpack_zip(Path(args.from_zip), args.dest_name)
    elif args.check:
        check_raw()
    else:
        print("No action. Use --demo, --check, or --from-zip PATH")
        print(PKLOT_HINT)
        print(CNR_HINT)
        check_raw()


if __name__ == "__main__":
    main()
