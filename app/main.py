import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from . import database as db
from .config import AVAILABLE_MODELS, IMAGES_DIR, STATIC_DIR, TEMPLATES_DIR
from .models import GenerateRequest
from .ollama import validate_ollama
from .prompt_bridge import vary_prompt
from .queue_manager import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("=" * 80)
    print("Starting Ollama Image Generator UI...")
    print("=" * 80)

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
        print("\n[WARNING] The application will start but image generation may not work.")
        print("[WARNING] Please ensure Ollama is installed and has image generation models.")
        print("[WARNING] Install models with: ollama pull <model-name>\n")

    print("\n[Database] Initializing database...")
    await db.init_db()
    print("[Database] ✓ Database initialized")

    print("[Storage] Creating images directory...")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[Storage] ✓ Images directory: {IMAGES_DIR}")

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


app = FastAPI(title="Ollama Image Generator", lifespan=lifespan)

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
        "index.html",
        {
            "request": request,
            "models": AVAILABLE_MODELS,
            "images": images,
            "queue": queue_status
        }
    )


@app.get("/gallery", response_class=HTMLResponse)
async def gallery(request: Request):
    """Image gallery page."""
    images = await db.get_images(limit=100)
    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "images": images
        }
    )


@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    """Queue management page."""
    images = await db.get_images(limit=None)
    queue_status = await queue_manager.get_queue_status()
    return templates.TemplateResponse(
        "queue.html",
        {
            "request": request,
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

    # Handle "All Models" selection
    models_to_use = []
    if request.model == "__all__":
        models_to_use = [model["id"] for model in AVAILABLE_MODELS]
    else:
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
    for _ in range(count):
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
                    pre_varied_prompt=shared_varied_prompt
                )
            else:
                job = await queue_manager.add_job(
                    request.prompt.strip(),
                    model,
                    vary_mode=vary_mode_for_jobs,
                    width=request.width,
                    height=request.height
                )
            jobs.append({"job_id": job.id, "status": job.status})

    if len(jobs) == 1:
        return jobs[0]
    return {"jobs": jobs, "count": len(jobs)}


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


# ============ HTMX Partial Routes ============

@app.get("/partials/queue", response_class=HTMLResponse)
async def queue_partial(request: Request):
    """Return queue HTML partial for htmx updates."""
    queue_status = await queue_manager.get_queue_status()
    return templates.TemplateResponse(
        "partials/queue.html",
        {"request": request, "queue": queue_status}
    )


@app.get("/partials/recent-images", response_class=HTMLResponse)
async def recent_images_partial(request: Request):
    """Return recent images HTML partial for htmx updates."""
    images = await db.get_images(limit=None)
    return templates.TemplateResponse(
        "partials/recent_images.html",
        {"request": request, "images": images}
    )
