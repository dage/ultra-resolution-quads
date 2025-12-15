import json

# Load original workflow
with open("experiments/iterate_t2i/workflows/comfyui_hallucination_test_comfyui_workflow.json", "r") as f:
    wf = json.load(f)

# 1. Add Context Image Loader (Node 100)
wf["100"] = {
    "inputs": {
        "image": "context_placeholder.png",  # Will be patched by renderer
        "upload": "image",
    },
    "class_type": "LoadImage",
}

# 2. Modify Positive Prompt (Node 6) to use TextEncodeQwenImageEdit
# Original Node 6: CLIPTextEncode
# New Node 6: TextEncodeQwenImageEdit
wf["6"]["class_type"] = "TextEncodeQwenImageEdit"
wf["6"]["inputs"] = {
    "text": "Make the image ultrasharp... (will be patched)",
    "clip": ["16", 0],  # Connect to CLIPLoaderGGUF
    "image": ["100", 0],  # Connect to Context Image
    # "vae": ["12", 0] # Optional, let's include it
}

# 3. Update Prompt Text (will be patched by renderer, but set default here)
# The renderer will append instructions.

# 4. Ensure CLIPLoaderGGUF (16) uses 'qwen_image' type?
# The user asked to "research", and perplexity suggested it.
# Node 6 name "TextEncodeQwenImageEdit" strongly implies it needs specific Qwen features.
# I'll update it to 'qwen_image' to be safe, assuming the node expects it.
# If it fails, I'll revert.
# wf["16"]["inputs"]["type"] = "qwen_image"
# UPDATE: I'll keep stable_diffusion first. If it errors, I'll change it.
# Reason: The UNET (13) is connected to KSampler. KSampler takes Model (13) and Positive (6).
# Positive (6) output must be compatible with Model (13).
# If Node 6 outputs SD Conditioning, it should match Model 13 (SD).
# If I change CLIPLoader to 'qwen_image', it might produce Qwen embeddings?
# But Node 6 converts them?
# Let's stick to 'stable_diffusion' as a baseline.

# 5. Save
with open("experiments/iterate_t2i/workflows/genzoom_context_redsquare_qwen_workflow.json", "w") as f:
    json.dump(wf, f, indent=2)

print("Created V2 Workflow.")
