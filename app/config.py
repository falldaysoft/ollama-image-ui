import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
IMAGES_DIR = BASE_DIR / "images"
UPLOADS_DIR = BASE_DIR / "uploads"  # Reference images for edits
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Database
DATABASE_PATH = DATA_DIR / "ollama_ui.db"

# Qwen-Image-2.1 via a patched stable-diffusion.cpp build (see qwen/README.md).
# SDCPP_DIR holds build/bin/sd-cli and models/.
SDCPP_DIR = Path(os.environ.get("SDCPP_DIR", BASE_DIR / "sdcpp")).expanduser()
QWEN_MODEL_ID = "qwen-image-2.1"
QWEN_DEFAULT_STEPS = 4  # 4-7; 6 adds ~25s for a little more detail
QWEN_REF_SCALE = 1.0  # Reference image area as a fraction of the output area

# Available models. "backend" selects the generator; only "qwen" accepts a reference image.
AVAILABLE_MODELS = [
    {"id": QWEN_MODEL_ID, "name": "Qwen Image 2.1", "backend": "qwen"},
    {"id": "x/flux2-klein:4b-fp4", "name": "Flux2 Klein (4B FP4)", "backend": "ollama"},
    {"id": "x/z-image-turbo", "name": "Z-Image Turbo", "backend": "ollama"},
]

DEFAULT_MODEL = QWEN_MODEL_ID


def model_backend(model_id: str) -> str:
    for model in AVAILABLE_MODELS:
        if model["id"] == model_id:
            return model["backend"]
    return "ollama"


def supports_reference(model_id: str) -> bool:
    return model_backend(model_id) == "qwen"


# Server settings
HOST = "0.0.0.0"
PORT = 8000
