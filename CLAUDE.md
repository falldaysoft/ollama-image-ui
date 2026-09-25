# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image Generation Web UI - a FastAPI-based web application for creating and editing images with local models: Qwen-Image-2.1 via a patched stable-diffusion.cpp `sd-cli` (generation, and edits from a reference image), plus Ollama image models. Features an async job queue with real-time SSE progress updates and optional prompt expansion via a local PromptBridge model.

## Common Commands

```bash
# One step: create/activate .venv, install requirements if changed, start the server, print the URL
./start.sh

# Activate virtual environment (required before running)
source .venv/bin/activate

# Start the development server (hot reload enabled, runs on http://0.0.0.0:8000)
python3 run.py

# Install dependencies
pip install -r requirements.txt
```

There is no test suite, linter, or build step. Verify changes by running the server. Qwen needs sd.cpp and models at `SDCPP_DIR` (default `./sdcpp`, gitignored; see `qwen/README.md`); Ollama models need Ollama with the model pulled. Startup logs report what was found.

## Architecture

### Request Flow
```
User submits prompt → POST /api/generate → database + queue
→ QueueManager._process_queue() (single background worker, one job at a time)
→ Optional prompt variation via PromptBridge (app/prompt_bridge.py)
→ Dispatches on the model's backend (config.AVAILABLE_MODELS[].backend):
    qwen:   app/qwen.py runs sd-cli (-r <reference> for edits), writes straight into images/
    ollama: runs `ollama run [--width W] [--height H] <model> <prompt>` as subprocess
→ Parses output stream for progress updates
→ Broadcasts via SSE to all connected clients
→ Saves image to disk + database
```

### Key Components

- **`app/main.py`** - FastAPI routes, lifespan (validates Ollama, inits DB, starts queue). Page routes render Jinja templates; `/partials/*` return HTMX fragments; `/api/*` are JSON.
- **`app/queue_manager.py`** - In-memory `asyncio.Queue` backed by the `jobs` table. On startup, resets `processing` jobs to `pending` and re-enqueues all pending jobs. Cancelled jobs are skipped when dequeued; `force` cancel kills the running generation task.
- **`app/ollama.py`** - Ollama CLI integration. The CLI writes the image into the **current working directory**; `generate_image()` snapshots existing `*.png`/`*.jpg` in cwd before running, then finds the new file and moves it into `images/`. Progress parsing strips ANSI codes and extracts percentages.
- **`app/qwen.py`** - Qwen-Image-2.1 through `sd-cli` (port of the original `edit.sh`): Viggle turbo LoRA (downloaded and fused by `app/fuse_lora.py` on first run), its sigma schedule shifted for the output resolution, 4-7 steps. Output size defaults to the reference's aspect at ~0.79 MP. Progress comes from sd-cli's log stage markers and `|===>| i/n` sampling bars. Cancelling the task kills sd-cli (it holds most of a 24 GB machine's memory).
- **`app/prompt_bridge.py`** - Lazily loads `retowyss/PromptBridge-0.6b-Alpha` via transformers/torch (~1.2GB download on first use). Runs in a thread pool behind an asyncio lock. Vary modes: `expand`, `expand_concise`, `expand_keywords`.
- **`app/database.py`** - Async SQLite (aiosqlite). Schema migrations live in `init_db()` as `ALTER TABLE ... ADD COLUMN` wrapped in try/except — add new columns the same way.
- **`app/models.py`** - Pydantic request/response models.
- **`app/config.py`** - Paths (incl. `SDCPP_DIR`, `UPLOADS_DIR`), host/port, `AVAILABLE_MODELS` (each with a `backend`), `DEFAULT_MODEL`.
- **`app/static/app.js`** - Frontend JS with SSE handling, debounced updates.
- **`templates/`** - Jinja2 templates with HTMX integration (`partials/` for fragments).

### "All Models" Generation

When `model == "__all__"`, `/api/generate` creates one job per entry in `AVAILABLE_MODELS`. If a vary mode is set, the prompt is varied once up front and passed as `pre_varied_prompt` (stored as `varied_prompt`) so every model gets the same prompt; jobs with `varied_prompt` already set skip variation in the worker.

### Reference Images (Edits)

`POST /api/references` (upload) and `POST /api/references/from-image/{id}` (gallery image) save an upright RGB PNG into `uploads/` and return its filename; `/api/generate` takes it as `reference_image`. Gallery images are copied so deleting them doesn't break queued jobs. Only `qwen`-backend models accept a reference; with one, "All Models" means only those. Jobs and images store `reference_image`, `seed` (random per job unless given; stepped by one per count) and `steps`.

### Real-Time Updates

SSE endpoint at `/api/queue/stream` (each subscriber gets its own asyncio.Queue fed by `_broadcast`) pushes: status, job_added, job_started, job_progress, job_completed, job_failed, job_cancelled. Keep-alive pings every 15 seconds.

### Data Storage

- SQLite database: `data/ollama_ui.db` (tables: `jobs`, `images`). Images store both the final `prompt` and `original_prompt` (pre-variation).
- Generated images: `images/` directory; reference images: `uploads/`

### Adding New Models

Edit `AVAILABLE_MODELS` list in `app/config.py` (`backend: "ollama"` for Ollama models).


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
