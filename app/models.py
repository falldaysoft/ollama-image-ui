from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from .config import DEFAULT_MODEL


class GenerateRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL
    vary_mode: Optional[str] = None  # None, "expand", or "expand_concise"
    count: int = 1  # Number of generations to queue
    width: Optional[int] = None  # Image width
    height: Optional[int] = None  # Image height
    reference_image: Optional[str] = None  # Filename in uploads/ (from /api/references)
    seed: Optional[int] = None  # None = random per job
    steps: Optional[int] = None  # Qwen sampling steps (4-7)


class JobResponse(BaseModel):
    id: str
    prompt: str
    model: str
    status: str
    image_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    vary_mode: Optional[str] = None  # None, "expand", or "expand_concise"
    varied_prompt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    reference_image: Optional[str] = None
    seed: Optional[int] = None
    steps: Optional[int] = None


class ImageResponse(BaseModel):
    id: str
    filename: str
    prompt: str
    model: str
    original_prompt: Optional[str] = None
    created_at: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    reference_image: Optional[str] = None
    seed: Optional[int] = None
    steps: Optional[int] = None


class QueueStatus(BaseModel):
    pending: int
    processing: int
    jobs: list[JobResponse]


class SSEEvent(BaseModel):
    event: str
    data: dict
