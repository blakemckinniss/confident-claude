# ComfyUI Management

Manage ComfyUI service. Argument: `start`, `restart`, or `stop`

## Paths
- Script: `/home/jinx/ai/comfyui/start_optimized.sh`
- Ports: 8188 (ComfyUI), 8189 (Wildcard Editor)

## Actions

**stop**: Kill existing processes
```bash
fuser -k 8188/tcp 8189/tcp 2>/dev/null
```

**start**: Run start script in background
```bash
/home/jinx/ai/comfyui/start_optimized.sh
```
Run in background, check output for "To see the GUI go to" to confirm success.

**restart**: Stop then start (execute both in sequence)

## Expected Output
- RTX 5090 detected with ~32GB VRAM
- Server ready message: `To see the GUI go to: http://0.0.0.0:8188`
- Impact-Subpack may fail (missing ultralytics) - non-critical

## Semantic Aliases
When user says any of these, use this command:
- "restart comfy" / "restart comfyui"
- "start comfy" / "start comfyui"
- "stop comfy" / "stop comfyui"
- "kill comfy"
