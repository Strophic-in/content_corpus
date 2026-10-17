"""LTX-2.5 (distilled, int8) text-to-video+audio as a ComfyUI API graph.

Mirrors Comfy-Org/workflow_templates templates/video_ltx2_5_t2v.json — two-stage
distilled sampling (half-size pass, 2x latent upscale, short refine), audio and
video denoised together — with the template's prompt enhancer removed and its
math/primitive nodes folded into constants. Positional widget values are resolved
to input names from the live /object_info, so a renamed input fails validation
instead of a paid render.

With a guide picture (`guide`: a file already uploaded to ComfyUI's input folder)
the shot is image-to-video, as in templates/video_ltx2_5_i2v.json: the picture,
preprocessed (LTXVPreprocess, compression 18), is written into the first frame of
the half-size latent at strength 0.7 and again into the upscaled latent at 1.0.
Our picture arrives already cut to the shot's size, so the template's resize
node is left out.
"""

from __future__ import annotations

import math

FPS = 24


def frames_for(seconds: float, pad_s: float = 0.35, max_s: float = 12.0) -> int:
    """Legal LTX frame count (8n + 1) covering `seconds` plus a short pause."""
    n = math.ceil((min(max_s, seconds + pad_s) * FPS) / 8)
    return 8 * n + 1


UNET = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
TE = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
VVAE, AVAE = "ltx-2.5-video-vae-bf16.safetensors", "ltx-2.5-audio-vae-bf16.safetensors"
UPS = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"


def nodes(shot: dict, frames: int, prefix: str, guide: str | None = None) -> dict:
    W, H = shot["width"], shot["height"]
    graph = {
        "unet": ("UNETLoader", {}, [UNET, "default"]),
        "vvae": ("VAELoader", {}, [VVAE]),
        "avae": ("VAELoader", {}, [AVAE]),
        "clip": ("CLIPLoader", {}, [TE, "ltxv", "default"]),
        "ups": ("LatentUpscaleModelLoader", {}, [UPS]),
        "pos": ("CLIPTextEncode", {"clip": ["clip", 0]}, [shot["prompt"]]),
        "neg": ("CLIPTextEncode", {"clip": ["clip", 0]}, [shot["negative"]]),
        "cond": ("LTXVConditioning", {"positive": ["pos", 0], "negative": ["neg", 0]}, [float(FPS)]),
        "lat_v": ("EmptyLTXVLatentVideo", {}, [W // 2, H // 2, frames, 1]),
        "lat_a": ("LTXVEmptyLatentAudio", {"audio_vae": ["avae", 0]}, [frames, FPS, 1]),
        "lat_av": ("LTXVConcatAVLatent", {"video_latent": ["lat_v", 0], "audio_latent": ["lat_a", 0]}, []),
        "noise1": ("RandomNoise", {}, [int(shot["seed"])]),
        "guide1": ("LTXVDualCFGGuider", {"model": ["unet", 0], "positive": ["cond", 0], "negative": ["cond", 1]}, [1, 1]),
        "samp1": ("KSamplerSelect", {}, ["euler_ancestral"]),
        "sig1": ("ManualSigmas", {}, ["1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"]),
        "run1": ("SamplerCustomAdvanced", {"noise": ["noise1", 0], "guider": ["guide1", 0], "sampler": ["samp1", 0],
                                           "sigmas": ["sig1", 0], "latent_image": ["lat_av", 0]}, []),
        "sep1": ("LTXVSeparateAVLatent", {"av_latent": ["run1", 0]}, []),
        "up": ("LTXVLatentUpsampler", {"samples": ["sep1", 0], "upscale_model": ["ups", 0], "vae": ["vvae", 0]}, []),
        "lat_av2": ("LTXVConcatAVLatent", {"video_latent": ["up", 0], "audio_latent": ["sep1", 1]}, []),
        "noise2": ("RandomNoise", {}, [42]),
        "guide2": ("LTXVDualCFGGuider", {"model": ["unet", 0], "positive": ["cond", 0], "negative": ["cond", 1]}, [1, 1]),
        "samp2": ("KSamplerSelect", {}, ["euler_ancestral"]),
        "sig2": ("ManualSigmas", {}, ["0.85, 0.7250, 0.4219, 0.0"]),
        "run2": ("SamplerCustomAdvanced", {"noise": ["noise2", 0], "guider": ["guide2", 0], "sampler": ["samp2", 0],
                                           "sigmas": ["sig2", 0], "latent_image": ["lat_av2", 0]}, []),
        "sep2": ("LTXVSeparateAVLatent", {"av_latent": ["run2", 0]}, []),
        "dec_v": ("VAEDecodeTiled", {"samples": ["sep2", 0], "vae": ["vvae", 0]}, [512, 64, 64, 16]),
        "dec_a": ("LTXVAudioVAEDecode", {"samples": ["sep2", 1], "audio_vae": ["avae", 0]}, []),
        "video": ("CreateVideo", {"images": ["dec_v", 0], "audio": ["dec_a", 0]}, [float(FPS)]),
        "save": ("SaveVideo", {"video": ["video", 0]}, [prefix, "auto", "auto"]),
    }
    if guide:
        graph.update({
            "img": ("LoadImage", {}, [guide]),
            "pre": ("LTXVPreprocess", {"image": ["img", 0]}, [18]),
            "i2v1": ("LTXVImgToVideoInplace", {"vae": ["vvae", 0], "image": ["pre", 0], "latent": ["lat_v", 0]},
                     [0.7, False]),
            "i2v2": ("LTXVImgToVideoInplace", {"vae": ["vvae", 0], "image": ["pre", 0], "latent": ["up", 0]},
                     [1.0, False]),
        })
        graph["lat_av"] = ("LTXVConcatAVLatent", {"video_latent": ["i2v1", 0], "audio_latent": ["lat_a", 0]}, [])
        graph["lat_av2"] = ("LTXVConcatAVLatent", {"video_latent": ["i2v2", 0], "audio_latent": ["sep1", 1]}, [])
    return graph


WIDGETS = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COMFY_DYNAMICCOMBO_V3"}


def _is_widget(d) -> bool:
    t = d[0]
    if isinstance(t, list):
        return True
    opts = d[1] if len(d) > 1 and isinstance(d[1], dict) else {}
    return bool(set(t.split(",")) & WIDGETS) or "widgetType" in opts


def _choices(d):
    t = d[0]
    if isinstance(t, list):
        return t
    opts = d[1].get("options") if len(d) > 1 and isinstance(d[1], dict) else None
    if t == "COMBO":
        return opts
    if t == "COMFY_DYNAMICCOMBO_V3" and opts:
        return [o["key"] for o in opts]
    return None


def build(info: dict, spec: dict) -> tuple[dict, list[str]]:
    graph, problems = {}, []
    for nid, (cls, links, pos) in spec.items():
        s = info.get(cls)
        if not s:
            problems.append(f"missing node {cls}")
            continue
        order = s.get("input_order") or {}
        names = list(order.get("required", s["input"].get("required", {}))) + \
            list(order.get("optional", s["input"].get("optional", {})))
        decl = {**s["input"].get("required", {}), **s["input"].get("optional", {})}
        free = [n for n in names if _is_widget(decl[n]) and n not in links]
        inputs = {**links, **dict(zip(free, pos))}
        for name, val in inputs.items():
            ch = _choices(decl.get(name, [None]))
            if ch is not None and not isinstance(val, list) and val not in ch:
                problems.append(f"{nid}.{name}={val!r} not in {list(ch)[:6]}")
        graph[nid] = {"class_type": cls, "inputs": inputs}
    return graph, problems
