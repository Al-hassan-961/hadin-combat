# HADIN-COMBAT AI Models

Details on training the four neural models and exporting them to ONNX for the
C++ core. All training is standard PyTorch; only inference ships to the device.

---

## 1. Pose Estimator (`pose.onnx`)

**Task:** single-person 2D keypoint detection.

- **Backbone:** MobileNetV3-Small / EfficientNet-Lite for edge deployment.
- **Head:** stacked hourglass or SimpleBaseline heatmap head (COCO 17 keypoints).
- **Loss:** MSE over heatmaps + Ohem.
- **Input:** `[1,3,H,W]` float RGB, normalized with ImageNet stats.
- **Output:** `[1,17,3]` `(x, y, score)`.

**Training:**
```bash
# e.g. torchvision KeypointRCNN / pose estimation repo (COCO 2017)
python train_pose.py --backbone mobilenet_v3_small \
    --epochs 60 --batch 64 --lr 1e-3 --img-size 224
```

**Export:**
```bash
python -m torch.onnx.export \
    --model best_pose.pt \
    --input torch.randn(1,3,224,224) \
    --export_path models/pose.onnx \
    --opset 13
```

---

## 2. Style Encoder (`style_encoder.onnx`) — Fighting DNA

**Task:** compress a sequence of poses into a fixed-size latent fingerprint.

- **Architecture:** sequence **autoencoder** (LSTM/GRU or Transformer encoder +
  decoder) with a 64-dim bottleneck.
- **Input:** `[B, T, K*2]` — `T` frames, each a flattened `(x, y)` pose.
- **Output:** `[B, 64]` latent embedding.
- **Loss:** reconstruction MSE + KL (variational variant) to regularize the
  latent space.
- **Purpose:** the latent is the **Fighting-DNA vector** fed to the opponent
  generator and the co-evolution policy.

**Training:**
```bash
# dataset: sequences of labeled fighting poses (striking, grappling, defensive)
python train_style_encoder.py \
    --seq-len 32 --latent-dim 64 --epochs 40 --lr 1e-3
```

**Export:**
```bash
python -m torch.onnx.export --model style_ae.pt \
    --input torch.randn(1,32,34) --export_path models/style_encoder.onnx --opset 13
```

---

## 3. Opponent Generator (`opponent_generator.onnx`) — Diffusion

**Task:** turn a Fighting-DNA latent + difficulty into a concrete opponent pose.

- **Architecture:** conditional **diffusion model** (DDPM or latent diffusion)
  conditioned on the style latent and a difficulty scalar.
- **Input:** `[1, latent_dim + 1]` (latent with difficulty appended).
- **Output:** `[1, K*2]` normalized opponent pose `(x, y)`.
- **Training:** standard denoising objective `L = E[ ||ε - ε_θ||² ]` with
  guidance weight to tune difficulty.

**Training:**
```bash
python train_opponent_diffusion.py \
    --latent-dim 64 --steps 1000 --epochs 100 --lr 2e-4 \
    --guidance 1.5
```

**Export:**
```bash
python -m torch.onnx.export --model opponent_diffusion.pt \
    --input torch.randn(1,65) --export_path models/opponent_generator.onnx --opset 13
```

---

## 4. Co-Evolution (`coevolution.onnx`) — PPO Policy

**Task:** decide the next difficulty and opponent latent adjustment so both
athlete and AI improve (co-evolution).

- **Algorithm:** **PPO** (Proximal Policy Optimization) over the environment
  defined by athlete skill progression.
- **State:** `[win_rate, progress, avg_response, sessions] + latent`.
- **Action:** continuous `(next_difficulty, latent_delta)`.
- **Reward:** reward for a challenging-but-winnable opponent that maximizes
  long-term athlete progress.

**Training:**
```bash
python train_coevolution_ppo.py \
    --steps 1_000_000 --clip 0.2 --lr 3e-4 \
    --reward-mix 0.5   # balance athlete win + improvement
```

**Export:**
```bash
python -m torch.onnx.export --model coev_policy.pt \
    --input torch.randn(1,68) --export_path models/coevolution.onnx --opset 13
```

---

## Export & Verification

- Use **ONNX opset 13** or newer for broad Runtime compatibility.
- Verify with `onnxruntime` after export:
  ```bash
  python -c "import onnxruntime as ort; s=ort.InferenceSession('models/pose.onnx'); print(s.get_inputs()[0].name)"
  ```
- Export all four models before first run; if absent, the backend falls back to
  MediaPipe for pose estimation and degrades gracefully for the others.

---

## Data Pipeline

1. Capture labeled pose sequences from real sparring sessions.
2. Normalize keypoints relative to torso length (scale/translation invariant).
3. Split into sliding windows of `T=32` frames.
4. Augment with jitter, mirroring, and speed perturbations.
