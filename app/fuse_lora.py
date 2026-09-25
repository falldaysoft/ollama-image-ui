#!/usr/bin/env python3
"""Fuse a Qwen-Image-2.1 LoRA's separate img_mlp.gate_layer / img_mlp.proj adapters into a
single img_mlp.gate_up adapter, matching GGUF checkpoints that store the fused tensor.

sd.cpp computes gate_up as [gate_layer; proj] (gate first), so the fused adapter is exact:
    A = [A_gate; A_proj]            (2r x in)
    B = [[B_gate, 0], [0, B_proj]]  (2*inter x 2r)
Pure numpy; bf16 is handled as raw uint16 (bf16 zero is 0x0000).

Usage: fuse_lora.py in.safetensors out.safetensors
"""
import json
import struct
import sys

import numpy as np


def load(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
        data = f.read()
    meta = header.pop("__metadata__", None)
    tensors = {}
    for k, v in header.items():
        assert v["dtype"] == "BF16", (k, v["dtype"])
        s, e = v["data_offsets"]
        tensors[k] = np.frombuffer(data[s:e], dtype=np.uint16).reshape(v["shape"])
    return tensors, meta


def save(path, tensors, meta):
    header, offset, blobs = {}, 0, []
    for k in sorted(tensors):
        b = np.ascontiguousarray(tensors[k]).tobytes()
        header[k] = {"dtype": "BF16", "shape": list(tensors[k].shape), "data_offsets": [offset, offset + len(b)]}
        offset += len(b)
        blobs.append(b)
    if meta:
        header["__metadata__"] = meta
    h = json.dumps(header, separators=(",", ":")).encode()
    h += b" " * (-len(h) % 8)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(h)))
        f.write(h)
        for b in blobs:
            f.write(b)


def main(src, dst):
    t, meta = load(src)
    out = dict(t)
    fused = 0
    for k in [k for k in t if ".img_mlp.gate_layer.lora_A." in k]:
        base = k.split(".img_mlp.gate_layer.")[0] + ".img_mlp."
        a_g, b_g = out.pop(base + "gate_layer.lora_A.weight"), out.pop(base + "gate_layer.lora_B.weight")
        a_p, b_p = out.pop(base + "proj.lora_A.weight"), out.pop(base + "proj.lora_B.weight")
        r_g, r_p = a_g.shape[0], a_p.shape[0]
        b = np.zeros((b_g.shape[0] + b_p.shape[0], r_g + r_p), dtype=np.uint16)
        b[: b_g.shape[0], :r_g] = b_g
        b[b_g.shape[0]:, r_g:] = b_p
        out[base + "gate_up.lora_A.weight"] = np.concatenate([a_g, a_p], axis=0)
        out[base + "gate_up.lora_B.weight"] = b
        fused += 1
    # Without alpha tensors sd.cpp uses scale 1.0, which matches alpha == rank in the source adapter.
    assert not any(k.endswith(".alpha") for k in out), "alpha tensors present; rank change would alter scale"
    save(dst, out, meta)
    print(f"fused {fused} img_mlp pairs, {len(t)} -> {len(out)} tensors, wrote {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
