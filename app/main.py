import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from . import database as db
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import AVAILABLE_MODELS, DEFAULT_MODEL, IMAGES_DIR, STATIC_DIR, TEMPLATES_DIR, UPLOADS_DIR, supports_reference
from .models import GenerateRequest
from .ollama import validate_ollama
from .qwen import MAX_STEPS, MIN_STEPS, validate_qwen
from .prompt_bridge import vary_prompt
from .queue_manager import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("=" * 80)
    print("Starting Image Generator UI...")
    print("=" * 80)

    # Validate the Qwen Image (sd.cpp) installation
    print("\n[Validation] Checking Qwen Image (sd.cpp)...")
    qwen_ok, qwen_message = validate_qwen()
    print(f"[Validation] {'✓' if qwen_ok else '✗'} {qwen_message}")
    if not qwen_ok:
        print("[WARNING] Qwen Image generation will fail. Set SDCPP_DIR to the sd.cpp checkout (see qwen/README.md).")

    # Validate Ollama installation
    print("\n[Validation] Checking Ollama installation...")
    validation = await validate_ollama()

    if validation.success:
        print(f"[Validation] ✓ {validation.message}")
        if validation.image_models_found:
            print(f"[Validation] ✓ Image models available:")
            for model in validation.image_models_found:
                print(f"              - {model}")
    else:
        print(f"[Validation] ✗ {validation.message}")
        if validation.models_found:
            print(f"[Validation]   Non-image models found: {', '.join(validation.models_found[:5])}")
        print("\n[WARNING] Ollama models may not work.")
        print("[WARNING] Install models with: ollama pull <model-name>\n")

    print("\n[Database] Initializing database...")
    await db.init_db()
    print("[Database] ✓ Database initialized")

    print("[Storage] Creating images directory...")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[Storage] ✓ Images directory: {IMAGES_DIR}")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[Storage] ✓ Reference images directory: {UPLOADS_DIR}")

    print("[Queue] Starting job queue manager...")
    await queue_manager.start()
    print("[Queue] ✓ Queue manager started")

    print("\n" + "=" * 80)
    print("Server ready!")
    print("=" * 80 + "\n")

    yield

    # Shutdown
    print("\n[Shutdown] Stopping queue manager...")
    await queue_manager.stop()
    print("[Shutdown] ✓ Queue manager stopped")


app = FastAPI(title="Image Generator", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ============ Page Routes ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main generation page."""
    images = await db.get_images(limit=None)
    queue_status = await queue_manager.get_queue_status()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "models": AVAILABLE_MODELS,
            "default_model": DEFAULT_MODEL,
            "steps_range": range(MIN_STEPS, MAX_STEPS + 1),
            "images": images,
            "queue": queue_status
        }
    )


@app.get("/gallery", response_class=HTMLResponse)
async def gallery(request: Request):
    """Image gallery page."""
    images = await db.get_images(limit=100)
    return templates.TemplateResponse(
        request,
        "gallery.html",
        {"images": images}
    )


@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    """Queue management page."""
    images = await db.get_images(limit=None)
    queue_status = await queue_manager.get_queue_status()
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "queue": queue_status,
            "images": images
        }
    )


# ============ API Routes ============

@app.post("/api/generate")
async def generate(request: GenerateRequest):
    """Queue a new image generation job."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    # Clamp count to reasonable range
    count = max(1, min(request.count, 100))

    reference_image = None
    if request.reference_image:
        reference_image = Path(request.reference_image).name
        if not (UPLOADS_DIR / reference_image).exists():
            raise HTTPException(status_code=400, detail="Reference image not found; upload it again")

    # Handle "All Models" selection
    models_to_use = []
    if request.model == "__all__":
        models_to_use = [model["id"] for model in AVAILABLE_MODELS]
        if reference_image:
            # Only some models can edit; "All Models" means all of those
            models_to_use = [m for m in models_to_use if supports_reference(m)]
    else:
        if reference_image and not supports_reference(request.model):
            raise HTTPException(status_code=400, detail="This model can't use a reference image")
        models_to_use = [request.model]

    # If using "All Models" with prompt variation, vary the prompt once upfront
    # so all models use the same variation
    shared_varied_prompt = None
    vary_mode_for_jobs = request.vary_mode
    if request.model == "__all__" and request.vary_mode:
        try:
            shared_varied_prompt = await vary_prompt(request.prompt.strip(), mode=request.vary_mode)
            # Don't vary again in individual jobs
            vary_mode_for_jobs = None
        except Exception as e:
            print(f"[DEBUG] Failed to vary prompt for all models: {e}")
            # Fall back to varying in each job
            shared_varied_prompt = None
            vary_mode_for_jobs = request.vary_mode

    jobs = []
    for i in range(count):
        # A fixed seed would repeat the same image; step it for each extra generation
        seed = request.seed + i if request.seed is not None else None
        for model in models_to_use:
            # If we have a shared varied prompt, use it as the prompt
            # and pass the original as the "varied_prompt" metadata
            if shared_varied_prompt:
                job = await queue_manager.add_job(
                    request.prompt.strip(),
                    model,
                    vary_mode=None,  # Don't vary again
                    width=request.width,
                    height=request.height,
                    pre_varied_prompt=shared_varied_prompt,
                    reference_image=reference_image,
                    seed=seed,
                    steps=request.steps
                )
            else:
                job = await queue_manager.add_job(
                    request.prompt.strip(),
                    model,
                    vary_mode=vary_mode_for_jobs,
                    width=request.width,
                    height=request.height,
                    reference_image=reference_image,
                    seed=seed,
                    steps=request.steps
                )
            jobs.append({"job_id": job.id, "status": job.status})

    if len(jobs) == 1:
        return jobs[0]
    return {"jobs": jobs, "count": len(jobs)}


def _save_reference(source) -> dict:
    """Normalize an image to an upright RGB PNG in uploads/ (sd.cpp reads PNG/JPEG only)."""
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        # The reference is scaled to about the output area anyway; cap huge photos
        img.thumbnail((2048, 2048))
        filename = f"{uuid.uuid4()}.png"
        img.save(UPLOADS_DIR / filename)
        return {"filename": filename, "url": f"/uploads/{filename}", "width": img.width, "height": img.height}


@app.post("/api/references")
async def upload_reference(file: UploadFile = File(...)):
    """Upload a reference image for editing."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return await asyncio.to_thread(_save_reference, file.file)
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Not a supported image file")


@app.post("/api/references/from-image/{image_id}")
async def reference_from_image(image_id: str):
    """Use a gallery image as the reference. It's copied so deleting it won't break queued jobs."""
    image = await db.get_image(image_id)
    if not image or not (IMAGES_DIR / image["filename"]).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return await asyncio.to_thread(_save_reference, IMAGES_DIR / image["filename"])


@app.get("/api/queue")
async def get_queue():
    """Get current queue status."""
    return await queue_manager.get_queue_status()


@app.get("/api/queue/stream")
async def queue_stream():
    """SSE endpoint for real-time queue updates."""
    return EventSourceResponse(queue_manager.subscribe())


@app.delete("/api/queue/{job_id}")
async def cancel_job(job_id: str, force: bool = False):
    """Cancel a job. Use ?force=true to cancel processing jobs."""
    success = await queue_manager.cancel_job(job_id, force=force)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Job not found or cannot be cancelled"
        )
    return {"status": "cancelled"}


@app.post("/api/queue/cancel-all")
async def cancel_all_jobs():
    """Cancel all pending jobs."""
    cancelled_count = await queue_manager.cancel_all_jobs()
    return {"status": "cancelled", "count": cancelled_count}


@app.get("/api/images")
async def list_images(limit: int = 50, offset: int = 0):
    """List generated images."""
    images = await db.get_images(limit=limit, offset=offset)
    return {"images": images}


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: str):
    """Delete an image."""
    image = await db.get_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Delete file
    image_path = IMAGES_DIR / image["filename"]
    if image_path.exists():
        os.remove(image_path)

    # Delete from database
    await db.delete_image(image_id)
    return {"status": "deleted"}


@app.get("/images/{filename}")
async def serve_image(filename: str):
    """Serve an image file."""
    # Sanitize filename to prevent directory traversal
    safe_filename = Path(filename).name
    image_path = IMAGES_DIR / safe_filename

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(image_path)


@app.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve a reference image."""
    image_path = UPLOADS_DIR / Path(filename).name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")
    return FileResponse(image_path)


# ============ HTMX Partial Routes ============

@app.get("/partials/queue", response_class=HTMLResponse)
async def queue_partial(request: Request):
    """Return queue HTML partial for htmx updates."""
    queue_status = await queue_manager.get_queue_status()
    return templates.TemplateResponse(
        request,
        "partials/queue.html",
        {"queue": queue_status}
    )


@app.get("/partials/recent-images", response_class=HTMLResponse)
async def recent_images_partial(request: Request):
    """Return recent images HTML partial for htmx updates."""
    images = await db.get_images(limit=None)
    return templates.TemplateResponse(
        request,
        "partials/recent_images.html",
        {"images": images}
    )
