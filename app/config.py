from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
IMAGES_DIR = BASE_DIR / "images"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Database
DATABASE_PATH = DATA_DIR / "ollama_ui.db"

# Available models
AVAILABLE_MODELS = [
    {"id": "x/flux2-klein:4b-fp4", "name": "Flux2 Klein (4B FP4)"},
    {"id": "x/z-image-turbo", "name": "Z-Image Turbo"},
]

DEFAULT_MODEL = "x/flux2-klein:4b-fp4"

# Server settings
HOST = "0.0.0.0"
PORT = 8000
