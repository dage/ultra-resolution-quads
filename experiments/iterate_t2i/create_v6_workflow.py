import json

# V6 Workflow: Differential Diffusion + InpaintModelConditioning
# Tile Size: 256. Canvas: 512.

wf = {
    "3": {  # KSampler
        "inputs": {
            "seed": 0,
            "steps": 8,
            "cfg": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 0.1,  # Tunable
            "model": ["104", 0],  # From DifferentialDiffusion
            "positive": ["105", 0],  # From InpaintModelConditioning
            "negative": ["105", 1],  # From InpaintModelConditioning
            "latent_image": ["105", 2],  # From InpaintModelConditioning
        },
        "class_type": "KSampler",
    },
    "6": {  # Positive Prompt (Qwen)
        "inputs": {"prompt": "Texture... (patched)", "clip": ["16", 0], "image": ["100", 0]},
        "class_type": "TextEncodeQwenImageEdit",
    },
    "7": {  # Negative Prompt
        "inputs": {"text": "low quality, blurry", "clip": ["16", 0]},
        "class_type": "CLIPTextEncode",
    },
    "8": {  # VAE Decode
        "inputs": {"samples": ["3", 0], "vae": ["12", 0]},
        "class_type": "VAEDecode",
    },
    "9": {  # Save
        "inputs": {"filename_prefix": "GenZoomV6", "images": ["103", 0]},
        "class_type": "SaveImage",
    },
    "12": {"inputs": {"vae_name": "ae.safetensors"}, "class_type": "VAELoader"},
    "13": {  # Model
        "inputs": {"unet_name": "z_image_turbo-Q5_K_S.gguf"},
        "class_type": "UnetLoaderGGUF",
    },
    "16": {  # CLIP
        "inputs": {"clip_name": "Qwen3-4B-Instruct-2507-Q5_K_M.gguf", "type": "qwen_image"},
        "class_type": "CLIPLoaderGGUF",
    },
    "100": {  # Context Image
        "inputs": {"image": "ctx.png", "upload": "image"},
        "class_type": "LoadImage",
    },
    "101": {  # Mask Image (Blurred)
        "inputs": {"image": "mask.png", "upload": "image"},
        "class_type": "LoadImage",
    },
    "103": {  # Image Crop
        "inputs": {"image": ["8", 0], "width": 256, "height": 256, "x": 128, "y": 128},
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

with open("experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json", "w") as f:
    json.dump(wf, f, indent=2)

print("Created V6 Workflow.")
