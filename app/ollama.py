import asyncio
import glob
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

from .config import IMAGES_DIR


@dataclass
class GenerationResult:
    success: bool
    image_path: Optional[Path] = None
    image_id: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ProgressUpdate:
    percent: int
    status: str


def parse_progress(line: str) -> Optional[ProgressUpdate]:
    """Parse progress from Ollama output line."""
    # Strip ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    line = ansi_escape.sub('', line)

    # Handle carriage returns - terminal progress bars use \r to overwrite the line
    # Keep only the content after the last \r (the current visible line)
    if '\r' in line:
        line = line.rsplit('\r', 1)[-1]

    line = line.strip()

    if not line:
        return None

    # Detect spinner characters (Braille patterns used by ollama for progress animation)
    # These indicate active processing
    spinner_chars = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    if any(c in line for c in spinner_chars):
        return ProgressUpdate(percent=-1, status="Generating image...")

    # Match patterns like "pulling manifest", "pulling sha256:...", "verifying sha256 digest"
    # and percentage patterns like "100%" or " 45%"
    percent_match = re.search(r'(\d+)%', line)

    if percent_match:
        percent = int(percent_match.group(1))
        # Extract a cleaner status message - don't include raw progress bar characters
        lower = line.lower()
        if 'pulling' in lower:
            status = f"Downloading... {percent}%"
        elif 'verifying' in lower:
            status = f"Verifying... {percent}%"
        elif 'generating' in lower:
            status = f"Generating... {percent}%"
        else:
            status = f"Processing... {percent}%"
        return ProgressUpdate(percent=percent, status=status)

    # For status lines without percentages, estimate based on keywords
    lower = line.lower()
    if 'pulling manifest' in lower:
        return ProgressUpdate(percent=2, status="Pulling manifest...")
    elif 'pulling' in lower and ('sha256' in lower or 'layer' in lower):
        return ProgressUpdate(percent=5, status="Downloading model layers...")
    elif 'verifying' in lower:
        return ProgressUpdate(percent=90, status="Verifying...")
    elif 'writing' in lower:
        return ProgressUpdate(percent=95, status="Writing...")
    elif 'success' in lower:
        return ProgressUpdate(percent=98, status="Model ready...")
    elif 'loading' in lower or 'loaded' in lower:
        return ProgressUpdate(percent=10, status="Loading model...")
    elif 'generating' in lower:
        return ProgressUpdate(percent=50, status="Generating image...")
    elif 'running' in lower:
        return ProgressUpdate(percent=15, status="Running model...")
    elif 'transferring' in lower:
        return ProgressUpdate(percent=20, status="Transferring context...")
    elif 'processing' in lower:
        return ProgressUpdate(percent=60, status="Processing...")
    elif 'saving' in lower or 'saved' in lower:
        return ProgressUpdate(percent=95, status="Saving image...")

    # Return generic update for any other non-empty output
    # Truncate very long lines for display
    display_status = line[:80] + "..." if len(line) > 80 else line
    return ProgressUpdate(percent=-1, status=display_status)


async def generate_image(
    prompt: str,
    model: str,
    progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None
) -> GenerationResult:
    """
    Generate an image using Ollama CLI.

    Ollama saves images to the current directory with pattern like:
    {prompt}-{timestamp}.png

    We run the command, find the new image file, and move it to our images directory.
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Get list of existing image files in cwd before generation
    cwd = Path.cwd()
    existing_pngs = set(cwd.glob("*.png"))
    existing_jpgs = set(cwd.glob("*.jpg")) | set(cwd.glob("*.jpeg"))

    try:
        # Build command with optional size parameters
        cmd = ["ollama", "run"]
        if width is not None:
            cmd.extend(["--width", str(width)])
        if height is not None:
            cmd.extend(["--height", str(height)])
        cmd.extend([model, prompt])

        # Run ollama CLI
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd)
        )

        # Read both streams for progress
        last_status = ""
        last_update_time = asyncio.get_event_loop().time()

        async def read_stream_chunks(stream, stream_name="stdout"):
            """Read stream in chunks to handle ollama's non-newline output."""
            nonlocal last_status, last_update_time
            all_data = []
            buffer = ""

            while True:
                try:
                    # Read small chunks with timeout
                    chunk = await asyncio.wait_for(stream.read(256), timeout=0.5)
                    if not chunk:
                        break
                    decoded = chunk.decode('utf-8', errors='replace')
                    all_data.append(decoded)
                    buffer += decoded

                    # Parse progress from the buffer
                    if progress_callback:
                        progress = parse_progress(buffer)
                        current_time = asyncio.get_event_loop().time()
                        # Send update if status changed or at least 0.5s passed
                        if progress and (progress.status != last_status or current_time - last_update_time > 0.5):
                            last_status = progress.status
                            last_update_time = current_time
                            try:
                                progress_callback(progress)
                            except Exception:
                                pass
                            buffer = ""  # Clear buffer after sending update

                except asyncio.TimeoutError:
                    # Timeout - check if process is still running and send heartbeat
                    if progress_callback and buffer:
                        progress = parse_progress(buffer)
                        if progress:
                            try:
                                progress_callback(progress)
                            except Exception:
                                pass
                            buffer = ""
                    continue

            return ''.join(all_data)

        # Read both streams concurrently
        stdout_task = asyncio.create_task(read_stream_chunks(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(read_stream_chunks(process.stderr, "stderr"))

        stdout_data, stderr_data = await asyncio.gather(stdout_task, stderr_task)
        await process.wait()

        if process.returncode != 0:
            error_msg = stderr_data if stderr_data else f"Process exited with code {process.returncode}"
            return GenerationResult(success=False, error=error_msg)

        # Find new png files created after running the command
        await asyncio.sleep(0.5)  # Brief delay to ensure file is written
        current_pngs = set(cwd.glob("*.png"))
        new_pngs = current_pngs - existing_pngs

        if not new_pngs:
            # Also check for jpg/jpeg files
            current_jpgs = set(cwd.glob("*.jpg")) | set(cwd.glob("*.jpeg"))
            new_jpgs = current_jpgs - existing_jpgs

            if new_jpgs:
                new_image = max(new_jpgs, key=lambda p: p.stat().st_mtime)
            else:
                return GenerationResult(
                    success=False,
                    error="No image file was created by Ollama"
                )
        else:
            # Get the most recently modified new png
            new_image = max(new_pngs, key=lambda p: p.stat().st_mtime)

        # Generate unique filename and move to images directory
        image_id = str(uuid.uuid4())
        ext = new_image.suffix
        filename = f"{image_id}{ext}"
        dest_path = IMAGES_DIR / filename

        shutil.move(str(new_image), str(dest_path))

        return GenerationResult(
            success=True,
            image_path=dest_path,
            image_id=image_id,
            filename=filename
        )

    except FileNotFoundError:
        return GenerationResult(
            success=False,
            error="Ollama CLI not found. Make sure Ollama is installed and in PATH."
        )
    except Exception as e:
        return GenerationResult(
            success=False,
            error=str(e)
        )


async def list_models() -> list[str]:
    """List available Ollama models."""
    try:
        process = await asyncio.create_subprocess_exec(
            "ollama", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return []

        # Parse output - skip header line
        lines = stdout.decode().strip().split("\n")[1:]
        models = [line.split()[0] for line in lines if line.strip()]
        return models

    except Exception:
        return []


@dataclass
class ValidationResult:
    success: bool
    message: str
    models_found: list[str]
    image_models_found: list[str]


async def validate_ollama() -> ValidationResult:
    """
    Validate that Ollama is installed, accessible, and has image generation models.

    Returns ValidationResult with:
    - success: True if Ollama is working and has image models
    - message: Human-readable status message
    - models_found: List of all models found
    - image_models_found: List of models that appear to be image generation models
    """
    try:
        # Check if ollama command exists and can execute
        process = await asyncio.create_subprocess_exec(
            "ollama", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            return ValidationResult(
                success=False,
                message=f"Ollama command failed: {error_msg}",
                models_found=[],
                image_models_found=[]
            )

        # Parse output - skip header line
        output = stdout.decode().strip()
        if not output:
            return ValidationResult(
                success=False,
                message="Ollama is installed but returned no output",
                models_found=[],
                image_models_found=[]
            )

        lines = output.split("\n")[1:]  # Skip header
        models = []
        for line in lines:
            if line.strip():
                # Extract model name (first column)
                parts = line.split()
                if parts:
                    models.append(parts[0])

        if not models:
            return ValidationResult(
                success=False,
                message="Ollama is installed but no models are available. Please install image generation models using 'ollama pull <model>'",
                models_found=[],
                image_models_found=[]
            )

        # Identify image generation models
        # Common patterns for image models: flux, stable-diffusion, sd, dall-e, imagen, midjourney, etc.
        image_model_keywords = [
            'flux', 'stable-diffusion', 'sd', 'dall-e', 'imagen',
            'midjourney', 'lcm', 'sdxl', 'kandinsky', 'playground',
            'image', 'img', 'vision', 'z-image', 'klein'
        ]

        image_models = []
        for model in models:
            model_lower = model.lower()
            if any(keyword in model_lower for keyword in image_model_keywords):
                image_models.append(model)

        if not image_models:
            return ValidationResult(
                success=False,
                message=f"Ollama has {len(models)} model(s) but none appear to be image generation models. Found: {', '.join(models[:3])}",
                models_found=models,
                image_models_found=[]
            )

        # Success!
        return ValidationResult(
            success=True,
            message=f"Ollama is ready with {len(image_models)} image generation model(s): {', '.join(image_models[:5])}",
            models_found=models,
            image_models_found=image_models
        )

    except FileNotFoundError:
        return ValidationResult(
            success=False,
            message="Ollama CLI not found. Please install Ollama from https://ollama.ai",
            models_found=[],
            image_models_found=[]
        )
    except Exception as e:
        return ValidationResult(
            success=False,
            message=f"Unexpected error validating Ollama: {str(e)}",
            models_found=[],
            image_models_found=[]
        )
