import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional
from datetime import datetime

from . import database as db
from .ollama import generate_image, ProgressUpdate


@dataclass
class Job:
    id: str
    prompt: str
    model: str
    status: str = "pending"
    image_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    progress: int = 0
    progress_status: str = ""


class QueueManager:
    def __init__(self):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._subscribers: list[asyncio.Queue] = []
        self._processing: Optional[Job] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background queue processor."""
        # Reset any jobs stuck in "processing" from a previous crash/restart
        processing_jobs = await db.get_jobs(status="processing")
        for job_data in processing_jobs:
            await db.update_job_status(job_data["id"], "pending")

        # Restore pending jobs from database
        pending_jobs = await db.get_jobs(status="pending")
        for job_data in pending_jobs:
            job = Job(
                id=job_data["id"],
                prompt=job_data["prompt"],
                model=job_data["model"],
                status="pending",
                created_at=job_data["created_at"]
            )
            await self._queue.put(job)

        self._task = asyncio.create_task(self._process_queue())

    async def stop(self):
        """Stop the queue processor."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_job(self, prompt: str, model: str) -> Job:
        """Add a new job to the queue."""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            prompt=prompt,
            model=model,
            status="pending",
            created_at=datetime.utcnow().isoformat()
        )

        # Save to database
        await db.create_job(job_id, prompt, model)

        # Add to queue
        await self._queue.put(job)

        # Notify subscribers
        await self._broadcast({
            "event": "job_added",
            "job": self._job_to_dict(job)
        })

        return job

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job (cannot cancel processing jobs)."""
        # We can't easily remove from asyncio.Queue, so we mark in DB
        job = await db.get_job(job_id)
        if job and job["status"] == "pending":
            await db.update_job_status(job_id, "cancelled")
            await self._broadcast({
                "event": "job_cancelled",
                "job_id": job_id
            })
            return True
        return False

    async def get_queue_status(self) -> dict:
        """Get current queue status."""
        pending_jobs = await db.get_jobs(status="pending")
        processing_jobs = await db.get_jobs(status="processing")

        # Merge in-memory progress state for the currently processing job
        all_jobs = []
        for job_data in pending_jobs + processing_jobs:
            if self._processing and job_data["id"] == self._processing.id:
                # Add current progress from in-memory state
                job_data["progress"] = self._processing.progress
                job_data["progress_status"] = self._processing.progress_status
            else:
                job_data["progress"] = 0
                job_data["progress_status"] = ""
            all_jobs.append(job_data)

        return {
            "pending": len(pending_jobs),
            "processing": len(processing_jobs),
            "jobs": all_jobs
        }

    async def subscribe(self) -> AsyncGenerator[dict, None]:
        """Subscribe to queue updates via SSE."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        print(f"[DEBUG] New SSE subscriber, total: {len(self._subscribers)}")

        try:
            # Send initial status
            status = await self.get_queue_status()
            yield {"event": "status", "data": json.dumps(status)}

            while True:
                try:
                    # Wait for events with timeout for keep-alive
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": event["event"], "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    # Send keep-alive ping
                    yield {"comment": "ping"}
        finally:
            self._subscribers.remove(queue)
            print(f"[DEBUG] SSE subscriber disconnected, remaining: {len(self._subscribers)}")

    async def _broadcast(self, event: dict):
        """Broadcast event to all subscribers."""
        print(f"[DEBUG] Broadcasting {event.get('event')} to {len(self._subscribers)} subscribers")
        for queue in self._subscribers:
            await queue.put(event)

    async def _process_queue(self):
        """Background task that processes jobs from the queue."""
        while True:
            try:
                job = await self._queue.get()

                # Check if job was cancelled while waiting
                db_job = await db.get_job(job.id)
                if db_job and db_job["status"] == "cancelled":
                    self._queue.task_done()
                    continue

                # Update status to processing
                self._processing = job
                job.status = "processing"
                await db.update_job_status(job.id, "processing")

                await self._broadcast({
                    "event": "job_started",
                    "job": self._job_to_dict(job)
                })

                # Send initial progress status
                job.progress = 0
                job.progress_status = "Initializing..."
                await self._broadcast({
                    "event": "job_progress",
                    "job_id": job.id,
                    "progress": job.progress,
                    "progress_status": job.progress_status
                })

                # Progress queue for async communication
                progress_queue: asyncio.Queue[ProgressUpdate] = asyncio.Queue()

                # Progress callback to queue updates
                def on_progress(update: ProgressUpdate):
                    try:
                        progress_queue.put_nowait(update)
                    except Exception:
                        pass

                # Task to process progress updates and broadcast them
                async def broadcast_progress():
                    last_broadcast_time = asyncio.get_event_loop().time()
                    last_progress = -1
                    last_status = ""
                    heartbeat_interval = 2.0  # Send heartbeat every 2 seconds if no updates
                    while True:
                        try:
                            update = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                            if update.percent >= 0:
                                job.progress = update.percent
                            job.progress_status = update.status

                            # Only broadcast when progress or status actually changes
                            if job.progress != last_progress or job.progress_status != last_status:
                                await self._broadcast({
                                    "event": "job_progress",
                                    "job_id": job.id,
                                    "progress": job.progress,
                                    "progress_status": job.progress_status
                                })
                                last_progress = job.progress
                                last_status = job.progress_status
                                last_broadcast_time = asyncio.get_event_loop().time()
                        except asyncio.TimeoutError:
                            # Send heartbeat if no updates for a while (keeps connection alive)
                            now = asyncio.get_event_loop().time()
                            if now - last_broadcast_time > heartbeat_interval:
                                await self._broadcast({
                                    "event": "job_progress",
                                    "job_id": job.id,
                                    "progress": job.progress,
                                    "progress_status": job.progress_status
                                })
                                last_broadcast_time = now
                            continue
                        except asyncio.CancelledError:
                            # Send final progress state before exiting
                            await self._broadcast({
                                "event": "job_progress",
                                "job_id": job.id,
                                "progress": job.progress,
                                "progress_status": job.progress_status
                            })
                            break

                # Start the broadcast task
                broadcast_task = asyncio.create_task(broadcast_progress())
                print(f"[DEBUG] Started broadcast task for job {job.id}")

                # Generate the image
                print(f"[DEBUG] Starting image generation for job {job.id}")
                result = await generate_image(job.prompt, job.model, on_progress)
                print(f"[DEBUG] Image generation complete for job {job.id}, success={result.success}")

                # Stop the broadcast task
                broadcast_task.cancel()
                try:
                    await broadcast_task
                except asyncio.CancelledError:
                    pass

                if result.success:
                    # Save image to database
                    await db.create_image(
                        result.image_id,
                        result.filename,
                        job.prompt,
                        job.model
                    )

                    # Update job status
                    job.status = "completed"
                    job.image_id = result.image_id
                    await db.update_job_status(job.id, "completed", image_id=result.image_id)

                    await self._broadcast({
                        "event": "job_completed",
                        "job": self._job_to_dict(job),
                        "image": {
                            "id": result.image_id,
                            "filename": result.filename,
                            "prompt": job.prompt,
                            "model": job.model
                        }
                    })
                else:
                    # Job failed
                    job.status = "failed"
                    job.error = result.error
                    await db.update_job_status(job.id, "failed", error=result.error)

                    await self._broadcast({
                        "event": "job_failed",
                        "job": self._job_to_dict(job)
                    })

                self._processing = None
                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but keep processing
                print(f"Error processing job: {e}")
                if self._processing:
                    await db.update_job_status(
                        self._processing.id,
                        "failed",
                        error=str(e)
                    )
                    self._processing = None

    def _job_to_dict(self, job: Job) -> dict:
        return {
            "id": job.id,
            "prompt": job.prompt,
            "model": job.model,
            "status": job.status,
            "image_id": job.image_id,
            "error": job.error,
            "created_at": job.created_at,
            "progress": job.progress,
            "progress_status": job.progress_status
        }


# Global queue manager instance
queue_manager = QueueManager()
