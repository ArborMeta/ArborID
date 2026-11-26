"""Export a BioCLIP image encoder to ONNX for the app (runs on CPU with onnxruntime, no PyTorch).

  python identify/export_onnx.py bioclip

Writes identify/model/<name>_visual.onnx (float32) and <name>_visual_w8.onnx (weight-only
8-bit, ~4x smaller), then checks both against PyTorch on a few training photos.
Input: float32 [N,3,224,224], CLIP-normalised. Output: L2-normalised embedding [N,D].
"""
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import open_clip
import torch
import onnx
from onnxruntime.quantization import matmul_nbits_quantizer as mq
from PIL import Image

HERE = Path(__file__).resolve().parent
MODEL = HERE / "model"
sys.path.insert(0, str(HERE))


class Visual(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.v = m.visual

    def forward(self, x):
        return torch.nn.functional.normalize(self.v(x), dim=-1)


def main():
    name = sys.argv[1]
    MODEL.mkdir(exist_ok=True)
    from ftmodel import create
    m, pre, _ = create(name)
    print(pre)
    net = Visual(m).eval()
    f32 = MODEL / f"{name}_visual.onnx"
    torch.onnx.export(net, (torch.randn(1, 3, 224, 224),), str(f32), input_names=["pixels"],
                      output_names=["embedding"], dynamic_axes={"pixels": {0: "n"}, "embedding": {0: "n"}},
                      opset_version=17, dynamo=False)
    # weight-only 8-bit (activations stay float): ~4x smaller, practically lossless
    i8 = MODEL / f"{name}_visual_w8.onnx"
    q = mq.MatMulNBitsQuantizer(onnx.load(str(f32)), bits=8, block_size=32, is_symmetric=True, accuracy_level=4)
    q.process()
    q.model.save_model_to_file(str(i8), use_external_data_format=False)

    imgs = sorted((HERE.parent / "images_train").glob("*.jpg"))[:16]
    x = torch.stack([pre(Image.open(p).convert("RGB")) for p in imgs])
    with torch.no_grad():
        ref = net(x).numpy()
    for f in (f32, i8):
        s = ort.InferenceSession(str(f), providers=["CPUExecutionProvider"])
        out = s.run(None, {"pixels": x.numpy()})[0]
        cos = (out * ref).sum(1)
        print(f"{f.name}: {f.stat().st_size / 1e6:.0f} MB, cosine vs PyTorch min {cos.min():.4f} mean {cos.mean():.4f}")


if __name__ == "__main__":
    main()
