# Parking Space Detection (CAI2840C)

**Authors:** Joaquin Gimeno, Fernando Jauregui, and Eliot Rudes  
Comparative experiment from the research proposal *Parking Space Detection Using Computer Vision and Deep Learning*: **MobileNetV3, VGG16, ResNet50** (+ simple CNN baseline) for parking-space occupancy classification on **PKLot** and **CNRPark-EXT**, with condition-level metrics and inference timing. Optional full-scene detection with **YOLOv8s** / **YOLO11n** remains off until YOLO-format labels exist.

## Quick start (demo — no large downloads)

```powershell
cd "...\Introduction to Computer Visio\Parking"
# Use Python 3.10–3.12 (TensorFlow has no wheels for 3.14 yet)
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_pipeline.py --demo --epochs 3 --models all
```

Omit `--models` (or pass `--models all`) to train the full proposal set: `baseline,mobilenetv3,vgg16,resnet50`. For a faster smoke test use `--models baseline,mobilenetv3`.

This creates a synthetic PKLot/CNR-style patch set, trains, evaluates, and writes results under `outputs/`.

### macOS

```bash
cd ".../Introduction to Computer Visio/Parking"
# If the project lives on a network volume, create the venv on the local disk
# (pip fails with "Directory not empty" errors on network shares):
python3 -m venv ~/parking_venv
~/parking_venv/bin/pip install -r requirements.txt
~/parking_venv/bin/python run_pipeline.py --demo --epochs 3
```

`src/__init__.py` automatically sets `KMP_DUPLICATE_LIB_OK=TRUE` and `OMP_NUM_THREADS=1` on macOS — without them the evaluation step crashes with SIGABRT because TensorFlow and scikit-learn each load their own copy of the OpenMP runtime.

## Full datasets

1. Download **PKLot**: https://web.inf.ufpr.br/vri/databases/parking-lot-database/
2. Download **CNRPark-EXT**: http://cnrpark.it/
3. Unpack into:

```text
data/raw/PKLot/PKLotSegmented/...
data/raw/CNRPark-EXT/PATCHES/{free|busy}/...
```

Or: `python -m src.download_datasets --from-zip PATH\to\archive.zip --dest-name PKLot`

Then:

```powershell
python -m src.prepare_data
python -m src.train --model all
python -m src.evaluate --model all
```

## Alignment with the research proposal

| Proposal item | Implementation |
|---------------|----------------|
| Baseline + MobileNetV3, VGG16, ResNet50 | `configs/default.yaml` → `models`; `src/models.py` |
| PKLot + CNRPark-EXT | `src/download_datasets.py`, `src/prepare_data.py` |
| Scene/camera-aware splits, fixed seed | `prepare_data.scene_aware_split`, `seed: 42` |
| Train-only augmentation (brightness, rotation, shifts, flip) | `augmentation` in config + `get_train_augmenter` |
| Acc / P / R / F1 / confusion matrices / size / inference time | `src/evaluate.py` |
| Condition-level + bootstrap CIs | weather, dataset, camera, scene; 95% CI |
| Failure-case review | `outputs/metrics/*_failures.csv` + notebook §5 |
| Optional YOLOv8s / YOLO11n | `yolo.enabled: false` until `data/processed/yolo/` labels exist |

## Project layout

| Path | Role |
|------|------|
| `configs/default.yaml` | Seed, splits, epochs, augmentation |
| `src/download_datasets.py` | Demo data / zip import / inventory check |
| `src/prepare_data.py` | Inventory + scene-aware train/val/test split |
| `src/models.py` | Baseline + transfer-learning classifiers |
| `src/train.py` / `src/evaluate.py` | Training and test metrics |
| `src/yolo_train.py` | Optional YOLOv8s / YOLO11n (off by default) |
| `notebooks/01_parking_occupancy_experiment.ipynb` | Guided notebook |
| `outputs/` | Checkpoints, figures, metric JSON/CSV |

## Metrics reported

Accuracy, precision, recall, F1 (and macro-F1), confusion matrices, 95% bootstrap CIs, model size (MB), mean inference ms/image and FPS, plus breakdowns by weather / dataset / camera / scene when metadata exists.

## Notes

- Use **Python 3.10–3.12** (TensorFlow still lacks wheels for 3.14).
- Image loading uses **PIL** so training works on Windows **UNC/network shares** (TF's `tf.io.read_file` often fails there).
- Splits prefer **scene/camera grouping** to reduce near-duplicate leakage (proposal §Procedure); with few scenes (demo) the code falls back to stratified image splits.
- Augmentation is applied **only on the training partition**.
- Set `yolo.enabled: true` in `configs/default.yaml` only after preparing YOLO-format full-scene labels under `data/processed/yolo/`.
- For faster I/O, you may copy the project to a local disk (e.g. `C:\Parking`) and run from there.
