# -*- coding: utf-8 -*-
"""Optional automatic scene-image generation through Replicate FLUX Schnell."""
from __future__ import annotations
import os, time
from pathlib import Path
from typing import Any
import requests

API_ROOT = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"

STYLE = ("editorial motion-graphics still for a premium vertical social video, 9:16 composition, "
         "high-end art direction, realistic photographic subject combined with bold cut-paper collage, "
         "clean off-white background, vivid acid-lime accent, charcoal black details, hard flash lighting, "
         "strong diagonal composition, oversized visual subject, tactile paper grain, sharp cutout edges, "
         "dynamic asymmetry, intentional negative space for separate typography, contemporary creator-video aesthetic. "
         "No text, no letters, no logos, no watermark, no UI gibberish, no captions.")


def scene_prompt(scene: dict[str, Any]) -> str:
    text = str(scene.get("spoken_text", "")).strip()
    intent = str(scene.get("intent", "explanation"))
    concept = str(scene.get("visual_concept", ""))
    specific = {
        "time": "A real overwhelmed creator at a cluttered desk, close-up hands working, oversized analog clock as a physical prop, energetic editorial crop.",
        "editing": "A real video editor workstation shown as a cinematic close-up, monitor displaying a coherent editing timeline with colorful footage thumbnails, hand on editing keyboard, layered video frames as physical collage pieces.",
        "ai": "A real creator interacting with a laptop that shows a clean visual workflow and a finished video preview, photographic subject and tangible paper-cut collage layers; no robot mascot.",
        "social": "A creator filming a vertical video with a smartphone rig, expressive real hands, phone screen showing a generic content preview, dynamic close-up.",
        "product": "Hero product photograph with tactile materials, dramatic studio lighting, close-up detail and bold editorial crop.",
        "beginning": "A creator starting a small project at a real desk, notebook, tools and early prototypes, candid documentary photography.",
        "process": "Close-up documentary photograph of hands performing the described task with the actual relevant tools and visible intermediate result.",
        "problem": "A visually clear real-world moment showing the concrete difficulty described, candid documentary photography, expressive hands and environmental clues.",
        "result": "A tangible finished result in a real environment, dramatic reveal framing and crisp details.",
        "money": "A real-world purchase or work setup with only contextually relevant physical objects; no readable invented amounts.",
        "emotion": "Candid cinematic portrait showing the emotion through body language and environmental context, not an emoji.",
        "decision": "A real person choosing between concrete options in a believable setting, close-up of gesture and object.",
    }.get(intent, "A concrete documentary-style scene illustrating the actual action and objects implied by the spoken sentence, not an abstract icon scene.")
    return f"Create one coherent still image for this spoken beat: {text!r}. Visual direction: {specific} Scene concept: {concept}. Art direction: {STYLE}"


def _token(explicit: str | None = None) -> str:
    token = (explicit or os.getenv("REPLICATE_API_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("أضف REPLICATE_API_TOKEN إلى Secrets لتفعيل التوليد التلقائي للصور.")
    return token


def generate_scene_image(scene: dict[str, Any], output_dir: str | Path, token: str | None = None, timeout: int = 180) -> Path:
    token = _token(token)
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    number = int(scene.get("scene_number", 0))
    target = out / f"scene_{number:03d}.webp"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "wait"}
    response = requests.post(API_ROOT, headers=headers, json={"input": {
        "prompt": scene_prompt(scene), "aspect_ratio": "9:16", "output_format": "webp",
        "output_quality": 90, "num_outputs": 1
    }}, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"Replicate رفض توليد المشهد {number}: HTTP {response.status_code} — {response.text[:350]}")
    data = response.json()
    deadline = time.time() + timeout
    while data.get("status") in {"starting", "processing"} and time.time() < deadline:
        time.sleep(2)
        poll_url = data.get("urls", {}).get("get")
        if not poll_url:
            break
        poll = requests.get(poll_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        poll.raise_for_status(); data = poll.json()
    if data.get("status") != "succeeded":
        raise RuntimeError(f"توليد المشهد {number} لم يكتمل: {data.get('error') or data.get('status')}")
    outputs = data.get("output")
    if isinstance(outputs, str): outputs = [outputs]
    if not outputs:
        raise RuntimeError(f"لم يُرجع المولد صورة للمشهد {number}.")
    image_response = requests.get(outputs[0], timeout=60)
    image_response.raise_for_status()
    if not image_response.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("استجابة مولد الصور ليست ملف صورة صالحًا.")
    target.write_bytes(image_response.content)
    return target
