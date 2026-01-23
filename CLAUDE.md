# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ollama Image Generation Web UI - a FastAPI-based web application providing a browser interface for generating images using local Ollama models. Features an async job queue with real-time SSE progress updates.

## Common Commands

```bash
# Activate virtual environment (required before running)
source .venv/bin/activate

# Start the development server (hot reload enabled, runs on http://0.0.0.0:8000)
python3 run.py

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Request Flow
```
User submits prompt → POST /api/generate → database + queue
→ QueueManager._process_queue() (background task)
→ Runs `ollama run <model> <prompt>` as subprocess
→ Parses output stream for progress updates
→ Broadcasts via SSE to all connected clients
→ Saves image to disk + database
```

### Key Components

- **`app/main.py`** - FastAPI routes and request handlers
- **`app/queue_manager.py`** - Async job queue with background processing, crash recovery (resets stuck jobs on startup)
- **`app/ollama.py`** - Ollama CLI integration with progress parsing (strips ANSI codes, parses percentages from terminal output)
- **`app/database.py`** - Async SQLite operations (aiosqlite)
- **`app/config.py`** - Configuration including available models
- **`app/static/app.js`** - Frontend JS with SSE handling, debounced updates
- **`templates/`** - Jinja2 templates with HTMX integration

### Real-Time Updates

SSE endpoint at `/api/events` pushes: status, job_added, job_started, job_progress, job_completed, job_failed, job_cancelled. Keep-alive pings every 15 seconds.

### Data Storage

- SQLite database: `data/ollama_ui.db` (tables: `jobs`, `images`)
- Generated images: `images/` directory

### Adding New Models

Edit `AVAILABLE_MODELS` list in `app/config.py`.
