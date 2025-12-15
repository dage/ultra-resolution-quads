import json

# V8 Workflow: Differential Diffusion + InpaintModelConditioning (512px tiles)
# Context canvas is handled by the renderer; this workflow just inpaints and then crops the center.

wf = {
    "3": {  # KSampler
        "inputs": {
            "seed": 0,
            "steps": 12,
            "cfg": 2.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 0.3,
            "model": ["104", 0],
            "positive": ["105", 0],
            "negative": ["105", 1],
            "latent_image": ["105", 2],
        },
        "class_type": "KSampler",
    },
    "6": {  # Positive prompt (Qwen)
        "inputs": {
            "prompt": "Generate the missing center part of this image. The surrounding texture shows the context. Ensure seamless blending. Preserve edges. Add sharp micro-detail, high fidelity, 8k.",
            "clip": ["16", 0],
            "image": ["100", 0],
        },
        "class_type": "TextEncodeQwenImageEdit",
    },
    "7": {  # Negative prompt
        "inputs": {"text": "low quality, blurry, soft focus, smeared edges, seam, border, frame", "clip": ["16", 0]},
        "class_type": "CLIPTextEncode",
    },
    "8": {  # VAE Decode
        "inputs": {"samples": ["3", 0], "vae": ["12", 0]},
        "class_type": "VAEDecode",
    },
    "9": {  # Save
        "inputs": {"filename_prefix": "GenZoomV8", "images": ["103", 0]},
        "class_type": "SaveImage",
    },
    "12": {"inputs": {"vae_name": "ae.safetensors"}, "class_type": "VAELoader"},
    "13": {"inputs": {"unet_name": "z_image_turbo-Q5_K_S.gguf"}, "class_type": "UnetLoaderGGUF"},
    "16": {
        "inputs": {"clip_name": "Qwen3-4B-Instruct-2507-Q5_K_M.gguf", "type": "qwen_image"},
        "class_type": "CLIPLoaderGGUF",
    },
    "100": {  # Context Image
        "inputs": {"image": "ctx.png", "upload": "image"},
        "class_type": "LoadImage",
    },
    "101": {  # Mask Image
        "inputs": {"image": "mask.png", "upload": "image"},
        "class_type": "LoadImage",
    },
    "103": {  # Crop center 512 from 768 canvas (pad=128)
        "inputs": {"image": ["8", 0], "width": 512, "height": 512, "x": 128, "y": 128},
        "class_type": "ImageCrop",
    },
    "104": {  # Differential Diffusion
        "inputs": {"model": ["13", 0]},
        "class_type": "DifferentialDiffusion",
    },
    "105": {  # Inpaint Model Conditioning
        "inputs": {
            "positive": ["6", 0],
            "negative": ["7", 0],
            "vae": ["12", 0],
            "pixels": ["100", 0],
            "mask": ["101", 1],
            "noise_mask": True,
        },
        "class_type": "InpaintModelConditioning",
    },
}

with open("experiments/iterate_t2i/workflows/genzoom_inpaint_neighbor_or_parent_512_workflow.json", "w") as f:
    json.dump(wf, f, indent=2)

print("Created V8 Workflow.")
