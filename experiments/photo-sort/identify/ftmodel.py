"""Load a BioCLIP model by name; "<name>-ft" = the base model with the fine-tuned image encoder from finetune.py."""
from pathlib import Path

import open_clip
import torch

HERE = Path(__file__).resolve().parent


def create(name):
    base = name[:-3] if name.endswith("-ft") else name
    model, _, preprocess = open_clip.create_model_and_transforms(f"hf-hub:imageomics/{base}")
    tokenizer = open_clip.get_tokenizer(f"hf-hub:imageomics/{base}")
    if name.endswith("-ft"):
        state = torch.load(HERE / "model" / f"{name}_visual.pt", map_location="cpu")
        model.visual.load_state_dict({k: v.float() for k, v in state.items()})
    return model, preprocess, tokenizer


def gpu_rest(t_start):
    """Share the GPU: with GPU_SHARE=0.5, rest as long as each batch took (GPU busy ~half the time)."""
    import os
    import time
    share = float(os.environ.get("GPU_SHARE", "1"))
    if share < 1:
        torch.cuda.synchronize()
        time.sleep((time.time() - t_start) * (1 / share - 1))
