import requests
import sys

COMFY_URL = "http://127.0.0.1:8000"
REQUIRED_UNETS = ["z_image_turbo-Q5_K_S.gguf"]
REQUIRED_CLIPS = ["Qwen3-4B-Instruct-2507-Q5_K_M.gguf"]
REQUIRED_VAES = ["ae.safetensors"]

def check_comfy():
    print(f"Checking ComfyUI at {COMFY_URL}...")
    try:
        resp = requests.get(f"{COMFY_URL}/system_stats", timeout=5)
        resp.raise_for_status()
        print("✅ ComfyUI is running.")
    except Exception as e:
        print(f"❌ Could not connect to ComfyUI: {e}")
        print("Please ensure ComfyUI is running on port 8188.")
        return False

    print("Checking for required models...")
    try:
        obj_info = requests.get(f"{COMFY_URL}/object_info", timeout=10).json()
    except Exception as e:
        print(f"❌ Failed to fetch object_info: {e}")
        return False

    # Check UNETs (UnetLoaderGGUF)
    # Note: different nodes might list models differently. 
    # UnetLoaderGGUF usually has input 'unet_name' which is a list of strings.
    
    missing = []

    def check_node_input_list(node_name, input_name, requirements, category_name):
        node = obj_info.get(node_name)
        if not node:
            print(f"⚠️  Node '{node_name}' not found. Cannot verify {category_name}.")
            return
        
        # input content is usually keys like "required", "optional"
        # "required": {"unet_name": (["file1", "file2"],), ...}
        
        inputs = node.get("input", {}).get("required", {})
        file_list = None
        
        # Find the input tuple
        for key, val in inputs.items():
            if key == input_name:
                file_list = val[0] # The first element is the list of options
                break
        
        if not file_list or not isinstance(file_list, list):
             print(f"⚠️  Could not parse file list for {node_name}.{input_name}")
             return

        for req in requirements:
            if req not in file_list:
                # Try simple matching?
                print(f"❌ Missing {category_name}: {req}")
                missing.append(req)
            else:
                print(f"✅ Found {category_name}: {req}")

    check_node_input_list("UnetLoaderGGUF", "unet_name", REQUIRED_UNETS, "GGUF UNET")
    check_node_input_list("CLIPLoaderGGUF", "clip_name", REQUIRED_CLIPS, "GGUF CLIP")
    check_node_input_list("VAELoader", "vae_name", REQUIRED_VAES, "VAE")
    
    if missing:
        print("\n❌ MISSING MODELS DETECTED!")
        print("Please download them to your ComfyUI models folders:")
        for m in missing:
            print(f" - {m}")
        return False
    
    print("\n✅ All systems go.")
    return True

if __name__ == "__main__":
    success = check_comfy()
    sys.exit(0 if success else 1)
