# Qwen Image 2.1 backend

The "Qwen Image 2.1" model runs Qwen-Image-2.1 through a patched
[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) `sd-cli`, with Viggle's
turbo LoRA. `app/qwen.py` builds the command (it's a port of the original `edit.sh`). With a
reference image it edits that image; without one it generates from the prompt. About 90 s per
image at 768x1024 on an M4 Pro with 24 GB.

## Setup

The app looks for sd.cpp in `SDCPP_DIR`, default `./sdcpp` (gitignored; a symlink works). It needs:

```
sdcpp/build/bin/sd-cli
sdcpp/models/diffusion_models/qwen_image_2.1-Q4_K.gguf
sdcpp/models/vae/qwen_image_2.1_vae_bf16.safetensors
sdcpp/models/text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf
sdcpp/models/text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf
```

The Viggle LoRA downloads into `sdcpp/models/loras/` and is converted with `app/fuse_lora.py` on
the first run. Startup logs say whether everything was found.

To build sd.cpp: check out stable-diffusion.cpp at `c678dfe7`, apply `sdcpp.patch` (prefix KV
cache, native RoPE, VAE fast path; the speed depends on it), then
`cmake -B build -DSD_METAL=ON && cmake --build build --target sd-cli -j`.

## Notes

* Size: blank width/height follow the reference image's aspect ratio at ~0.79 MP (768x1024 for
  text-to-image). Small text such as name tags only survives at about this size.
* Steps: 4-7. 6 adds ~25 s for a little more detail.
* Seed: random unless set; it's stored with each image, so "Reuse All" reproduces an image.
* Full-res runs use most of a 24 GB machine; close heavy apps if a run stalls. The text encoder
  is released after conditioning (`--params-backend te=disk`) to make room.
* Don't add `--mmap`: it produces garbage images in this sd.cpp build.

## Writing edit prompts

The model keeps anything the prompt doesn't clearly replace, including a subject's pose, and the
pose drags the original foreground along with it. For a new setting:

1. Lead with the scene: *"Replace the entire scene with …"*
2. Say what to remove: *"Remove the cash register, the food tray, the counter and the customer's hand."*
3. Give a new pose or action: *"sitting on the dock holding a mug of coffee"*
4. Describe the whole outfit, then *"Keep her face and long red hair unchanged."*
