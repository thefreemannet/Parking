"""Classification models: baseline CNN + MobileNetV3, VGG16, ResNet50 transfer learning."""
from __future__ import annotations

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers


def get_preprocess_fn(name: str):
    """Return a tf-friendly preprocess that maps RGB float [0,255] -> model input."""
    name = name.lower()
    if name == "baseline":
        return None  # model applies Rescaling internally
    if name == "mobilenetv3":
        return keras.applications.mobilenet_v3.preprocess_input
    if name == "vgg16":
        return keras.applications.vgg16.preprocess_input
    if name == "resnet50":
        return keras.applications.resnet50.preprocess_input
    raise ValueError(f"Unknown model: {name}")


def build_baseline(image_size: tuple[int, int], num_classes: int = 1) -> keras.Model:
    """Simple CNN baseline (proposal: simple CNN or majority-class predictor)."""
    inputs = keras.Input(shape=(*image_size, 3))
    x = layers.Rescaling(1.0 / 255)(inputs)
    x = layers.Conv2D(32, 3, activation="relu")(x)
    x = layers.MaxPooling2D()(x)
    x = layers.Conv2D(64, 3, activation="relu")(x)
    x = layers.MaxPooling2D()(x)
    x = layers.Conv2D(128, 3, activation="relu")(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(num_classes, activation="sigmoid")(x)
    return keras.Model(inputs, outputs, name="baseline_cnn")


def _backbone(name: str, image_size: tuple[int, int]) -> keras.Model:
    shape = (*image_size, 3)
    name = name.lower()
    if name == "mobilenetv3":
        base = keras.applications.MobileNetV3Small(
            input_shape=shape, include_top=False, weights="imagenet"
        )
    elif name == "vgg16":
        base = keras.applications.VGG16(input_shape=shape, include_top=False, weights="imagenet")
    elif name == "resnet50":
        base = keras.applications.ResNet50(input_shape=shape, include_top=False, weights="imagenet")
    else:
        raise ValueError(f"Unknown backbone: {name}")
    base.trainable = False
    return base


def build_transfer_model(
    name: str,
    image_size: tuple[int, int],
    learning_rate: float = 1e-4,
) -> keras.Model:
    """Transfer model expects inputs already preprocessed (see get_preprocess_fn)."""
    base = _backbone(name, image_size)
    inputs = keras.Input(shape=(*image_size, 3))
    x = base(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(1, activation="sigmoid")(x)
    model = keras.Model(inputs, outputs, name=name)
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="binary_crossentropy",
        metrics=["accuracy", keras.metrics.Precision(name="precision"), keras.metrics.Recall(name="recall")],
    )
    return model


def build_model(name: str, image_size: tuple[int, int], learning_rate: float = 1e-4) -> keras.Model:
    if name.lower() == "baseline":
        model = build_baseline(image_size)
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
            loss="binary_crossentropy",
            metrics=[
                "accuracy",
                keras.metrics.Precision(name="precision"),
                keras.metrics.Recall(name="recall"),
            ],
        )
        return model
    return build_transfer_model(name, image_size, learning_rate)


def get_train_augmenter(cfg: dict) -> keras.Sequential:
    aug = cfg.get("augmentation", {})
    ops = [
        layers.RandomBrightness(aug.get("brightness_delta", 0.15)),
        layers.RandomRotation(aug.get("rotation_range", 10) / 360.0),
        layers.RandomTranslation(
            aug.get("height_shift_range", 0.08),
            aug.get("width_shift_range", 0.08),
        ),
    ]
    if aug.get("horizontal_flip", True):
        ops.append(layers.RandomFlip("horizontal"))
    return keras.Sequential(ops, name="train_augmenter")
