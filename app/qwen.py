"""Qwen-Image-2.1 generation and editing through a patched stable-diffusion.cpp `sd-cli`.

Port of ~/temp/qwen/edit.sh: Viggle's DMD turbo LoRA sampled on its own sigma schedule with the
resolution-dependent shift Qwen-Image-2.1 applies, 4-7 steps, no CFG. With a reference image the
model edits it; without one it generates from the prompt alone. The speed depends on local sd.cpp
changes (prefix KV cache, native RoPE, VAE fast path); see qwen/sdcpp.patch.
"""
import asyncio
import math
import random
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .config import IMAGES_DIR, QWEN_DEFAULT_STEPS, QWEN_REF_SCALE, SDCPP_DIR
from .ollama import GenerationResult, ProgressUpdate

MODELS_DIR = SDCPP_DIR / "models"
SD_CLI = SDCPP_DIR / "build" / "bin" / "sd-cli"
DIFFUSION_MODEL = MODELS_DIR / "diffusion_models" / "qwen_image_2.1-Q4_K.gguf"
VAE = MODELS_DIR / "vae" / "qwen_image_2.1_vae_bf16.safetensors"
LLM = MODELS_DIR / "text_encoders" / "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
LLM_VISION = MODELS_DIR / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-F16.gguf"
LORA_DIR = MODELS_DIR / "loras"
LORA_SRC = LORA_DIR / "viggle-turbo-v0.2.1-r128.safetensors"
LORA_NAME = "viggle-turbo-v0.2.1-r128-fused"
LORA_URL = "https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo/resolve/main/Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors"

# Output area used when no size is given: 768x1024 (~0.79 MP). Small text (name tags, signs)
# only survives at about this size.
DEFAULT_AREA = 768 * 1024
DEFAULT_ASPECT = 768 / 1024

# Raw nodes from the Viggle README: keep 0.75/0.5/0.25 and split 1 -> 0.75 at the high-noise end.
RAW_SIGMAS = {
    4: [1.0, 0.75, 0.5, 0.25],
    5: [1.0, 0.875, 0.75, 0.5, 0.25],
    6: [1.0, 0.9375, 0.875, 0.75, 0.5, 0.25],
    7: [1.0, 0.9583, 0.9167, 0.875, 0.75, 0.5, 0.25],
}
MIN_STEPS, MAX_STEPS = min(RAW_SIGMAS), max(RAW_SIGMAS)

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
# "|=====>      | 2/4 - 11.07s/it" (sampling) vs "|#####      | 97/263 - 1.13GB/s" (weight loading)
PROGRESS_BAR = re.compile(r'\|([=>#\s]*)\|\s*(\d+)/(\d+)')

# Keep references to background prefetch processes so they get reaped.
_background: set[asyncio.Task] = set()


def random_seed() -> int:
    return random.randint(0, 2**31 - 1)


def clamp_steps(steps: Optional[int]) -> int:
    if steps is None:
        return QWEN_DEFAULT_STEPS
    return max(MIN_STEPS, min(MAX_STEPS, steps))


def output_size(width: Optional[int], height: Optional[int], reference: Optional[Path]) -> tuple[int, int]:
    """Output size in multiples of 16. Missing dimensions follow the reference image's aspect
    ratio (or 3:4 for text-to-image) at ~0.79 MP, rounded to multiples of 32 like edit.sh."""
    if width and height:
        return _round(width, 16), _round(height, 16)

    aspect = DEFAULT_ASPECT
    if reference is not None:
        with Image.open(reference) as img:
            aspect = img.width / img.height

    if width:
        return _round(width, 16), _round(width / aspect, 16)
    if height:
        return _round(height * aspect, 16), _round(height, 16)
    return _round(math.sqrt(DEFAULT_AREA * aspect), 32), _round(math.sqrt(DEFAULT_AREA / aspect), 32)


def _round(value: float, multiple: int) -> int:
    return max(multiple, round(value / multiple) * multiple)


def sigmas(width: int, height: int, steps: int) -> str:
    """Viggle's raw schedule with diffusers' exponential shift for this resolution
    (base_shift 0.5 @ 256 tokens, max_shift 0.9 @ 8192 tokens, 16px per token)."""
    seq = (width // 16) * (height // 16)
    mu = 0.5 + (0.9 - 0.5) * (seq - 256) / (8192 - 256)
    e = math.exp(mu)
    return ",".join("%.5f" % (e / (e + (1 / s - 1))) for s in RAW_SIGMAS[steps]) + ",0"


def missing_files() -> list[Path]:
    """Required files that don't exist. The LoRA is fetched on first use, so it isn't listed."""
    return [p for p in (SD_CLI, DIFFUSION_MODEL, VAE, LLM, LLM_VISION) if not p.exists()]


def validate_qwen() -> tuple[bool, str]:
    missing = missing_files()
    if missing:
        return False, "Qwen Image missing: " + ", ".join(str(p) for p in missing)
    return True, f"Qwen Image ready (sd.cpp at {SDCPP_DIR})"


async def ensure_lora(progress: Callable[[ProgressUpdate], None]) -> None:
    """Download Viggle's turbo LoRA and fuse its img_mlp adapters for the GGUF's fused tensor."""
    if (LORA_DIR / f"{LORA_NAME}.safetensors").exists():
        return
    LORA_DIR.mkdir(parents=True, exist_ok=True)
    if not LORA_SRC.exists():
        progress(ProgressUpdate(percent=1, status="Downloading turbo LoRA (first run)..."))
        process = await asyncio.create_subprocess_exec("curl", "-fL", "-o", str(LORA_SRC), LORA_URL)
        if await process.wait() != 0:
            LORA_SRC.unlink(missing_ok=True)
            raise RuntimeError("Failed to download the Viggle turbo LoRA")
    progress(ProgressUpdate(percent=2, status="Fusing turbo LoRA (first run)..."))
    from .fuse_lora import main as fuse_lora
    await asyncio.to_thread(fuse_lora, str(LORA_SRC), str(LORA_DIR / f"{LORA_NAME}.safetensors"))


async def _prefetch(*paths: Path) -> None:
    """Warm the OS file cache: sd.cpp loads each model only when first needed and reads at
    ~1.2 GB/s, so these reads overlap the VAE encode and the text encoder."""
    process = await asyncio.create_subprocess_exec(
        "cat", *map(str, paths),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()


def _start_prefetch() -> None:
    for group in ((LLM,), (DIFFUSION_MODEL, LORA_DIR / f"{LORA_NAME}.safetensors")):
        task = asyncio.create_task(_prefetch(*group))
        _background.add(task)
        task.add_done_callback(_background.discard)


@dataclass
class _Stage:
    marker: str
    percent: int
    status: str


# Log lines that mark progress through sd-cli's pipeline, with the status of what runs next.
STAGES = [
    _Stage("EDIT mode", 5, "Encoding reference image..."),
    _Stage("encode_first_stage completed", 12, "Encoding prompt..."),
    _Stage("get_learned_condition completed", 25, "Loading diffusion model..."),
    _Stage("prefix cache", 35, "Sampling..."),
    _Stage("sampling completed", 88, "Decoding image..."),
    _Stage("decode_first_stage completed", 97, "Saving image..."),
]
SAMPLING_START, SAMPLING_END = 35, 88


def parse_line(line: str) -> Optional[ProgressUpdate]:
    for stage in STAGES:
        if stage.marker in line:
            return ProgressUpdate(percent=stage.percent, status=stage.status)

    bar = PROGRESS_BAR.search(line)
    # Weight-loading bars are brief; the stage status says more
    if bar and "#" not in bar.group(1):
        done, total = int(bar.group(2)), int(bar.group(3))
        percent = SAMPLING_START + (SAMPLING_END - SAMPLING_START) * done // max(total, 1)
        return ProgressUpdate(percent=percent, status=f"Sampling step {done}/{total}...")
    return None


async def generate_image(
    prompt: str,
    progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    reference: Optional[Path] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
) -> GenerationResult:
    """Generate (reference=None) or edit (reference set) an image with Qwen-Image-2.1."""
    def progress(update: ProgressUpdate):
        if progress_callback:
            try:
                progress_callback(update)
            except Exception:
                pass

    missing = missing_files()
    if missing:
        return GenerationResult(success=False, error="Qwen Image files missing: " + ", ".join(map(str, missing)))
    if reference is not None and not reference.exists():
        return GenerationResult(success=False, error=f"Reference image not found: {reference.name}")

    try:
        await ensure_lora(progress)
    except Exception as e:
        return GenerationResult(success=False, error=str(e))

    steps = clamp_steps(steps)
    seed = random_seed() if seed is None else seed
    width, height = output_size(width, height, reference)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    image_id = str(uuid.uuid4())
    filename = f"{image_id}.png"
    dest_path = IMAGES_DIR / filename

    edit_args = []
    if reference is not None:
        ref_pixels = int(width * height * QWEN_REF_SCALE)
        edit_args = [
            "--llm_vision", str(LLM_VISION),
            "-r", str(reference),
            "--ref-image-args", f"vae_input_max_pixels={ref_pixels}",
        ]

    cmd = [
        str(SD_CLI),
        "--diffusion-model", str(DIFFUSION_MODEL),
        "--vae", str(VAE),
        "--llm", str(LLM),
        "--lora-model-dir", str(LORA_DIR), "--lora-apply-mode", "at_runtime",
        *edit_args,
        "-p", f"{prompt}<lora:{LORA_NAME}:1>",
        "--cfg-scale", "1.0", "--sampling-method", "euler", "--sigmas", sigmas(width, height, steps),
        "-W", str(width), "-H", str(height),
        "--diffusion-fa",
        # Load the text encoder on demand and release it after conditioning: frees ~5.4 GB
        # before the DiT prefill, without which a 24 GB Mac can stall for minutes.
        "--params-backend", "te=disk",
        "--seed", str(seed),
        "-o", str(dest_path),
    ]
    # Don't use --mmap: it produces garbage images in this sd.cpp build.

    progress(ProgressUpdate(percent=2, status="Loading models..."))
    _start_prefetch()

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(SDCPP_DIR),
    )

    tail: list[str] = []  # Recent log lines for error reports
    try:
        buffer = ""
        while True:
            chunk = await process.stdout.read(1024)
            if not chunk:
                break
            buffer += ANSI_ESCAPE.sub("", chunk.decode("utf-8", errors="replace"))
            *lines, buffer = re.split(r"[\r\n]", buffer)
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-20:]
                update = parse_line(line)
                if update:
                    progress(update)
        await process.wait()
    except asyncio.CancelledError:
        # sd-cli holds most of the machine's memory; don't leave it running.
        if process.returncode is None:
            process.kill()
            await process.wait()
        dest_path.unlink(missing_ok=True)
        raise

    if process.returncode != 0 or not dest_path.exists():
        detail = "\n".join(line for line in tail if not PROGRESS_BAR.search(line))
        return GenerationResult(
            success=False,
            error=f"sd-cli exited with code {process.returncode}\n{detail}".strip(),
        )

    return GenerationResult(
        success=True,
        image_path=dest_path,
        image_id=image_id,
        filename=filename,
        width=width,
        height=height,
        seed=seed,
    )
