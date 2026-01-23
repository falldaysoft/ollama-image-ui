"""PromptBridge integration for prompt variation/expansion."""

import asyncio
from functools import partial
from typing import Optional

# Global model state (lazy loaded)
_model = None
_tokenizer = None
_lock = asyncio.Lock()


def _load_model():
    """Load the PromptBridge model (called once on first use)."""
    global _model, _tokenizer

    if _model is not None:
        return

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_name = "retowyss/PromptBridge-0.6b-Alpha"

    print(f"[PromptBridge] Loading model {model_name}...")

    _tokenizer = AutoTokenizer.from_pretrained(model_name)
    _model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        device_map="auto"
    )

    print("[PromptBridge] Model loaded successfully")


def _vary_prompt_sync(prompt: str) -> str:
    """Synchronous prompt variation (runs in thread pool)."""
    _load_model()

    # Use "Expand the prompt" system instruction for richer image prompts
    system_instruction = "Expand the prompt"

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    text = _tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = _tokenizer(text, return_tensors="pt").to(_model.device)

    outputs = _model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
        pad_token_id=_tokenizer.eos_token_id
    )

    # Extract only the generated part
    generated_ids = outputs[0][inputs.input_ids.shape[-1]:]
    varied_prompt = _tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    return varied_prompt


async def vary_prompt(prompt: str) -> str:
    """
    Vary/expand a prompt using PromptBridge.

    This runs the model in a thread pool to avoid blocking the event loop.
    The model is lazily loaded on first use.

    Args:
        prompt: The original user prompt

    Returns:
        The varied/expanded prompt
    """
    async with _lock:
        loop = asyncio.get_event_loop()
        varied = await loop.run_in_executor(
            None,
            partial(_vary_prompt_sync, prompt)
        )
        return varied
