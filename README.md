# Image Generator

A web interface for creating and editing images with local models: Qwen Image 2.1 (through
stable-diffusion.cpp) for generation and reference-image edits, plus optional Ollama image models.

![Image Generator UI](screenshot.png)

## Quick Start

### Prerequisites

- Python 3.10 or newer
- For Qwen Image: a patched stable-diffusion.cpp build and the Qwen-Image-2.1 models. See [qwen/README.md](qwen/README.md).
- Optional: [Ollama](https://ollama.ai) with image models, for the Flux2 Klein and Z-Image Turbo options

### Setup

The quick way: `./start.sh` creates and activates `.venv`, installs dependencies (again whenever
`requirements.txt` changes), starts the server, and prints its URL once it's up.

Or step by step:

1. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   ```

2. **Activate the virtual environment:**
   ```bash
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the server:**
   ```bash
   python3 run.py
   ```

5. **Open your browser:**
   ```
   http://localhost:8000
   ```

That's it! You should see the image generation interface.

## How to Use

1. Enter a text prompt (e.g., "a cat wearing a hat")
2. To edit an image instead, attach a reference image: drop it on the form, paste it, or click to
   choose a file. Or pick an image in the gallery and click **Edit** (or press <kbd>E</kbd>).
3. Leave the size blank to follow the reference's aspect ratio, or set it
4. Click "Generate" (or "Edit Image")
5. Watch the progress bar as your image is created

Edit prompts work best when they say both what to change and what to keep; see
[qwen/README.md](qwen/README.md#writing-edit-prompts). Only Qwen Image accepts a reference image.

## Vary Prompt Feature

The **Vary Prompt** dropdown lets you automatically enhance your prompts using a local AI model ([PromptBridge](https://huggingface.co/retowyss/PromptBridge-0.6b-Alpha)):

- **None**: Use your prompt as-is
- **Expand**: Enriches simple prompts with more descriptive details (e.g., "cat" → "a fluffy orange tabby cat with bright green eyes, sitting upright with an alert expression")
- **Expand + Sentence**: Expands the prompt then condenses it into a single flowing sentence

The model downloads automatically on first use (~1.2GB). When generating with "All Models", the prompt is varied once and reused for consistency across all models.

## Adding More Models

Qwen Image's settings (sd.cpp location, default steps) are in `app/config.py`. To use different Ollama models, edit the `AVAILABLE_MODELS` list in `app/config.py` and restart the server.

## Troubleshooting

- **"Qwen Image files missing"**: Point `SDCPP_DIR` at the sd.cpp checkout, or symlink it to `./sdcpp`
- **"No models available"**: Make sure Ollama is running and you have image generation models installed
- **Port already in use**: Another app is using port 8000. Stop it or change the port in `run.py`
- **Images not generating**: Check that your Ollama models are properly installed with `ollama list`
