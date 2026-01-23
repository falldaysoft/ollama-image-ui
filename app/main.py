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
from .queue_manager import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    await db.init_db()
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    await queue_manager.start()
    yield
    # Shutdown
    await queue_manager.stop()


app = FastAPI(title="Ollama Image Generator", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ============ Page Routes ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main generation page."""
    images = await db.get_images(limit=12)
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


# ============ API Routes ============

@app.post("/api/generate")
async def generate(request: GenerateRequest):
    """Queue a new image generation job."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    job = await queue_manager.add_job(
        request.prompt.strip(),
        request.model,
        vary_prompt=request.vary_prompt
    )
    return {"job_id": job.id, "status": job.status}


@app.get("/api/queue")
async def get_queue():
    """Get current queue status."""
    return await queue_manager.get_queue_status()


@app.get("/api/queue/stream")
async def queue_stream():
    """SSE endpoint for real-time queue updates."""
    return EventSourceResponse(queue_manager.subscribe())


@app.delete("/api/queue/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a pending job."""
    success = await queue_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Job not found or cannot be cancelled"
        )
    return {"status": "cancelled"}


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
    images = await db.get_images(limit=12)
    return templates.TemplateResponse(
        "partials/recent_images.html",
        {"request": request, "images": images}
    )
