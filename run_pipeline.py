"""One-command pipeline: demo data -> prepare -> train -> evaluate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.download_datasets import create_demo_dataset
from src.evaluate import evaluate_model, summarize_all
from src.prepare_data import prepare
from src.train import train_one
from src.utils import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parking occupancy pipeline")
    parser.add_argument("--demo", action="store_true", help="Create synthetic demo data first")
    parser.add_argument("--epochs", type=int, default=None, help="Override training epochs")
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated model list (default: all from config)",
    )
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    if args.epochs is not None:
        cfg["epochs"] = args.epochs

    if args.demo:
        create_demo_dataset()

    prepare()

    names = cfg["models"] if not args.models else [m.strip() for m in args.models.split(",")]
    if not args.skip_train:
        for name in names:
            print(f"\n=== Training {name} ===")
            train_one(name, cfg)

    if not args.skip_eval:
        for name in names:
            ckpt = ROOT / "outputs" / "models" / f"{name}_best.keras"
            if ckpt.exists():
                print(f"\n=== Evaluating {name} ===")
                evaluate_model(name, cfg)
        summarize_all(cfg)

    print("\nPipeline finished. See outputs/metrics and outputs/figures.")


if __name__ == "__main__":
    main()
