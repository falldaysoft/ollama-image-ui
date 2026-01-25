from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "x/flux2-klein:4b-fp4"
    vary_mode: Optional[str] = None  # None, "expand", or "expand_concise"
    count: int = 1  # Number of generations to queue
    width: Optional[int] = None  # Image width
    height: Optional[int] = None  # Image height


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


class ImageResponse(BaseModel):
    id: str
    filename: str
    prompt: str
    model: str
    original_prompt: Optional[str] = None
    created_at: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class QueueStatus(BaseModel):
    pending: int
    processing: int
    jobs: list[JobResponse]


class SSEEvent(BaseModel):
    event: str
    data: dict
