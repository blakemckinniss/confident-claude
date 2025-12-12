# Plan: Install AI-Toolkit & Setup Z-Image-Turbo LoRA Training

## Quick Summary

| Step | Action | Time |
|------|--------|------|
| 1 | Clone ai-toolkit to `lora-training/` | 2 min |
| 2 | Create venv, install PyTorch + deps | 10 min |
| 3 | Configure HF token from existing `.env` | 1 min |
| 4 | Install Web UI (npm) | 3 min |
| 5 | Download Z-Image-Turbo + training adapter | 10 min |
| 6 | Create training config YAML | 2 min |
| **Total** | **Ready to train** | **~30 min** |

---

## Overview

Install [ostris/ai-toolkit](https://github.com/ostris/ai-toolkit) in `/home/jinx/ai/comfyui/lora-training` and configure it for training LoRAs on Z-Image-Turbo using the [de-distillation training adapter](https://huggingface.co/ostris/zimage_turbo_training_adapter).

**Initial Confidence: 95%** - Well-documented process, user has optimal hardware.

## User Environment (Confirmed)
- **GPU**: RTX 5090 (32GB VRAM) - Full settings, batch_size=2 possible
- **Node.js**: v24.11.0 - Web UI compatible
- **HF Token**: Exists at `/home/jinx/ai/comfyui/.env` (key: `HUGGINGFACE_API_KEY`)
- **Python**: 3.12.3

---

## Phase 1: Install AI-Toolkit

### Step 1.1: Create Directory & Clone Repository
```bash
mkdir -p /home/jinx/ai/comfyui/lora-training
cd /home/jinx/ai/comfyui/lora-training
git clone https://github.com/ostris/ai-toolkit.git
cd ai-toolkit
git submodule update --init --recursive
```

### Step 1.2: Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 1.3: Install PyTorch (CRITICAL - Must install first)
```bash
pip install --no-cache-dir torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
  --index-url https://download.pytorch.org/whl/cu126
```

### Step 1.4: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 1.5: Configure Hugging Face Token
Use existing token from ComfyUI (note: AI-toolkit uses `HF_TOKEN` variable name):
```bash
# Extract token and create .env with correct variable name
grep HUGGINGFACE_API_KEY /home/jinx/ai/comfyui/.env | sed 's/HUGGINGFACE_API_KEY/HF_TOKEN/' > .env
```

### Step 1.6: Install Web UI
```bash
cd /home/jinx/ai/comfyui/lora-training/ai-toolkit
npm install
npm run build
```

To start the Web UI later:
```bash
npm run start  # Access at http://localhost:8675
```

Optional security (if exposing to network):
```bash
export AI_TOOLKIT_AUTH="your_secure_token"
```

---

## Phase 2: Download Required Models

### Step 2.1: Download Z-Image-Turbo Base Model
The model will auto-download on first run, or can be pre-downloaded:
```bash
huggingface-cli download Tongyi-MAI/Z-Image-Turbo --local-dir models/z-image-turbo
```

### Step 2.2: Download Training Adapter
```bash
huggingface-cli download ostris/zimage_turbo_training_adapter --local-dir models/zimage_training_adapter
```

---

## Phase 3: Prepare Training Images

### Step 3.1: Upscale and Center Crop Images
Source: `/home/jinx/ai/comfyui/lora-training/upscale/`
Target: `/home/jinx/ai/comfyui/lora-training/ai-toolkit/datasets/my_lora/`

Create Python script to process images (upscale + center crop to 1024x1024):
```python
# process_images.py - DO NOT READ/DISPLAY images, only resize
from PIL import Image
import os
from pathlib import Path

src_dir = Path("/home/jinx/ai/comfyui/lora-training/upscale")
dst_dir = Path("/home/jinx/ai/comfyui/lora-training/ai-toolkit/datasets/my_lora")
dst_dir.mkdir(parents=True, exist_ok=True)

target_size = 1024

for i, img_path in enumerate(sorted(src_dir.glob("*")), 1):
    if img_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
        img = Image.open(img_path)

        # Upscale if needed (maintain aspect ratio first)
        w, h = img.size
        scale = max(target_size / w, target_size / h)
        if scale > 1:
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Center crop to 1024x1024
        w, h = img.size
        left = (w - target_size) // 2
        top = (h - target_size) // 2
        img = img.crop((left, top, left + target_size, top + target_size))

        # Save with sequential naming
        output_path = dst_dir / f"image_{i:03d}.png"
        img.save(output_path, "PNG")
        print(f"Processed: {img_path.name} -> {output_path.name}")

print(f"Done! {i} images processed to {dst_dir}")
```

### Step 3.2: Create Training Config YAML

Create `config/zimage_turbo_lora.yaml`:

```yaml
job: extension
config:
  name: "my_zimage_lora"
  process:
    - type: sd_trainer
      training_folder: "output/my_zimage_lora"
      device: cuda:0
      network:
        type: lora
        linear: 16
        linear_alpha: 16
      save:
        dtype: float16
        save_every: 250
        max_step_saves_to_keep: 4
      datasets:
        - folder_path: "datasets/my_lora"
          caption_ext: txt
          caption_dropout_rate: 0.05
          shuffle_tokens: false
          cache_latents_to_disk: true
          resolution: [1024, 1024]
      train:
        batch_size: 2  # RTX 5090 can handle 2
        steps: 3000
        gradient_accumulation_steps: 1
        train_unet: true
        train_text_encoder: true  # Enable with 32GB VRAM
        gradient_checkpointing: false  # Not needed with 32GB
        noise_scheduler: flowmatch
        optimizer: adamw8bit
        lr: 1e-4
        ema_config:
          use_ema: true
          ema_decay: 0.99
        dtype: bf16
      model:
        name_or_path: "Tongyi-MAI/Z-Image-Turbo"
        is_flux: false
        quantize: false
      sample:
        sampler: flowmatch
        sample_every: 250
        width: 1024
        height: 1024
        prompts:
          - "a photo of [trigger], professional photography"
          - "[trigger] in a garden, natural lighting"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 3.5
        sample_steps: 4
      # DE-DISTILLATION ADAPTER - Critical for Z-Image-Turbo
      adapter:
        path: "models/zimage_training_adapter"
        # Use v1 adapter (default) or try v2 for comparison
```

---

## Phase 4: Training Workflow

### Step 4.1: Prepare Dataset
1. Place 5-15 high-quality images in `datasets/my_lora/`
2. Create matching `.txt` caption files with trigger word (e.g., `image1.txt` containing `a photo of sks_style`)
3. Use distinctive trigger tokens (e.g., `sks_style`, `teach3r`) to avoid vocabulary conflicts

### Step 4.2: Run Training
```bash
cd /home/jinx/ai/comfyui/lora-training/ai-toolkit
source venv/bin/activate
python run.py config/zimage_turbo_lora.yaml
```

### Step 4.3: Monitor Training
- Samples generated every 250 steps in `output/my_zimage_lora/samples/`
- Checkpoints saved every 250 steps
- Watch for style convergence in periodic samples

---

## Phase 5: Use Trained LoRA in ComfyUI

### Step 5.1: Copy LoRA to ComfyUI
```bash
cp output/my_zimage_lora/my_zimage_lora.safetensors \
   /home/jinx/ai/comfyui/models/loras/
```

### Step 5.2: ComfyUI Workflow
1. Load Z-Image-Turbo base model
2. Apply LoRA with weight 0.8-1.0
3. Use trigger word in prompt
4. Use 4-step sampling (distilled speed preserved)

---

## Key Configuration Parameters

| Parameter | Recommended | Notes |
|-----------|-------------|-------|
| Steps | 2000-3000 | 3000 for 5-15 images |
| Batch Size | 1-2 | Higher destabilizes identity |
| Learning Rate | 1e-4 to 5e-5 | Lower for tight constraints |
| LoRA Rank | 8-16 | 16 for more detail capacity |
| Resolution | 1024x1024 | Z-Image sweet spot |
| Sample Every | 250 | Monitor convergence |

---

## VRAM - RTX 5090 Optimized Settings

With 32GB VRAM, use full performance settings:
```yaml
resolution: [1024, 1024]
batch_size: 2  # Can go higher, but 2 is stable
gradient_checkpointing: false  # Not needed with 32GB
train_text_encoder: true  # Can enable for better results
```

Expected training time: ~1 hour for 3000 steps.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `/home/jinx/ai/comfyui/lora-training/` | Create directory |
| `ai-toolkit/.env` | Create with HF token |
| `config/zimage_turbo_lora.yaml` | Create training config |
| `datasets/my_lora/` | Create for training images |

---

## Documentation Updates

After implementation:
- **CLAUDE.md**: Add section for LoRA training with ai-toolkit
- **docs/ADR.md**: Document training infrastructure decision

---

## Technical Debt & Risks

1. **Separate venv**: AI-toolkit uses its own venv, not ComfyUI's - intentional isolation
2. **PyTorch version**: AI-toolkit requires torch 2.7.0 with CUDA 12.6 - may differ from ComfyUI
3. **Disk space**: Z-Image-Turbo is ~24.6GB, training adapter is additional
4. **Long training**: >10k steps may break distillation (artifacts when adapter removed)

---

## Sources

- [GitHub - ostris/ai-toolkit](https://github.com/ostris/ai-toolkit)
- [Hugging Face - zimage_turbo_training_adapter](https://huggingface.co/ostris/zimage_turbo_training_adapter)
- [Training LoRA for Z-Image Turbo (Engineering Notes)](https://huggingface.co/blog/content-and-code/training-a-lora-for-z-image-turbo)
- [DeepWiki - AI Toolkit Installation](https://deepwiki.com/ostris/ai-toolkit/1.2-installation-and-setup)
- [12GB VRAM Training Experience](https://github.com/ostris/ai-toolkit/issues/550)
