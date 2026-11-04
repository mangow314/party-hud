"""Regenerate the raw images behind art/ with a local ComfyUI server.

Each entry in prompts.json records the exact prompt, seed and sampler settings of a shipped image.
ComfyUI renders a batch of `batch` images per seed; `pick` is the index we kept.
Output: scripts/art/raw/<name>.png. Then run decor.py (portraits) and crest_compose.py (crests).

Models (all Apache-2.0, see ASSETS.md), placed in ComfyUI's models/ folders:
  diffusion_models/flux-2-klein-4b.safetensors, text_encoders/qwen_3_4b.safetensors, vae/flux2-vae.safetensors
Results may differ slightly across GPUs and ComfyUI versions.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")


def post(path, body):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def graph(job):
    """Text-to-image graph for FLUX.2 [klein] 4B (step-distilled: 4 steps, cfg 1, empty negative prompt)."""
    w, h = job["width"], job["height"]
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "flux-2-klein-4b.safetensors", "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": job["text"]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": job["batch"]}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": job["seed"]}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": job["sampler"]}},
        "9": {"class_type": "Flux2Scheduler", "inputs": {"steps": job["steps"], "width": w, "height": h}},
        "10": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": job["cfg"]},
        },
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["7", 0],
                "guider": ["10", 0],
                "sampler": ["8", 0],
                "sigmas": ["9", 0],
                "latent_image": ["6", 0],
            },
        },
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {
            "class_type": "SaveImage",
            "inputs": {"images": ["12", 0], "filename_prefix": f"party-hud/{job['name']}"},
        },
    }


def run(job):
    pid = post("/prompt", {"prompt": graph(job)})["prompt_id"]
    for _ in range(900):
        hist = json.load(urllib.request.urlopen(f"{URL}/history/{pid}"))
        if pid in hist:
            if hist[pid].get("status", {}).get("status_str") == "error":
                sys.exit(f"{job['name']}: ComfyUI reported an error: {hist[pid]['status']}")
            images = [img for out in hist[pid]["outputs"].values() for img in out.get("images", [])]
            img = images[job["pick"]]
            q = urllib.parse.urlencode(
                {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            )
            with (
                urllib.request.urlopen(f"{URL}/view?{q}") as r,
                open(os.path.join(RAW, job["name"] + ".png"), "wb") as f,
            ):
                f.write(r.read())
            return
        time.sleep(1)
    sys.exit(f"{job['name']}: timed out")


if __name__ == "__main__":
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(HERE, "prompts.json")) as f:
        jobs = json.load(f)
    for job in jobs:
        if os.path.exists(os.path.join(RAW, job["name"] + ".png")):
            print("skip (exists)", job["name"])
            continue
        run(job)
        print("done", job["name"], flush=True)
