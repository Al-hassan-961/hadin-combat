# HADIN-COMBAT Models

Place your trained ONNX models in this directory. The backend reads the
following filenames (configurable via `.env`):

| File | Purpose | Input | Output |
|---|---|---|---|
| `pose.onnx` | Single-person 2D pose estimation | `[1,3,H,W]` RGB float | keypoints `(x, y, score)` |
| `style_encoder.onnx` | Sequence autoencoder bottleneck | `[B,T,K*2]` pose sequence | latent `[B,64]` |
| `opponent_generator.onnx` | Diffusion opponent pose sampler | latent + difficulty | opponent pose `(x, y)` |
| `coevolution.onnx` | Adaptation policy (PPO) | profile features + latent | `(difficulty, latent_delta)` |

> ⚠️ If `pose.onnx` is missing, the backend **automatically falls back to
> MediaPipe** for pose estimation, so the app still works. The other models
> are used only when their `.onnx` files are present.

## Downloading pre-trained models

> Pre-trained weights are not bundled in this repository. You can:

1. **Download community/your own ONNX pose models** from sources such as
   [ONNX Model Zoo](https://github.com/onnx/models) and place them as
   `models/pose.onnx`. For example, an exported MobileNetV3-SSD pose model
   or a TFLite-ported PoseNet converted to ONNX.

2. **Export your own** using the training pipelines described in
   [`docs/AI_MODELS.md`](../docs/AI_MODELS.md):
   ```bash
   python -m torch.onnx.export \
       --model model.pt --input input.pt \
       --export_path models/opponent_generator.onnx
   ```

## Expected model format

- Input/output tensors are **float32**, NCHW for images.
- The backend's C++ core expects:
  - Pose: `input[1,3,H,W]` → `output[1,N,3]` (or `[1,3,N]`) with `N` keypoints.
  - Style: `input[B,T,F]` → `output[B,latent]`.
  - Opponent: `input[1,latent+1]` (difficulty appended) → `output[1,K*2]`.
  - CoEvolution: `input[1,4+latent]` → `output[1,1+latent]`.

See [`docs/AI_MODELS.md`](../docs/AI_MODELS.md) for full details and
conversion tooling.
