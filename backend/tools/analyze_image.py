import os
import asyncio
import base64
import mimetypes
from pathlib import Path
import argparse
import random
from typing import List, Union, Optional

from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIConnectionError, APIStatusError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def _guess_mime(path: Union[str, Path]) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "image/png"

def encode_image_to_data_url(
    data: Union[bytes, str, Path],
    mime: Optional[str] = None,
) -> str:
    """
    Accepts raw bytes or a filesystem path; returns a data: URL suitable
    for OpenAI/OpenRouter Chat Completions image input.
    """
    if isinstance(data, str) and data.startswith("data:"):
        return data
    if isinstance(data, (str, Path)):
        p = Path(str(data))
        if p.exists():
            raw = p.read_bytes()
            mime = mime or _guess_mime(p)
        else:
            # Treat as literal content (e.g. HTML canvas export) rather than a file path
            # if it doesn't exist as a file.
            # But for this CLI tool, we expect file paths.
            raise FileNotFoundError(f"Image file not found: {p}")
    elif isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        mime = mime or "image/png"
    else:
        raise ValueError("encode_image_to_data_url expects bytes, data: URL, or existing file path")

    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"

async def analyze_images(
    image_paths: List[str], 
    prompt: str, 
    model: str = "qwen/qwen3-vl-8b-instruct"
) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables.")

    headers = {
        "X-Title": "ultra-resolution-quads-tools",
        "HTTP-Referer": "http://localhost",
    }

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,
        default_headers=headers,
    )

    # Build content list
    content_list = [{"type": "text", "text": prompt}]
    for img_path in image_paths:
        data_url = encode_image_to_data_url(img_path)
        content_list.append({
            "type": "image_url",
            "image_url": {"url": data_url}
        })

    messages = [{"role": "user", "content": content_list}]

    # Simple retry logic
    max_tries = 5
    base = 0.5
    
    for i in range(max_tries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages
            )
            return response.choices[0].message.content
        except (RateLimitError, APITimeoutError, APIConnectionError):
            if i == max_tries - 1:
                raise
            await asyncio.sleep(base * (2 ** i) + random.random() * 0.1)
        except APIStatusError as e:
            if e.status_code == 402: # Insufficient credits
                raise
            if e.status_code in (408, 429, 500, 502, 503, 504):
                if i == max_tries - 1:
                    raise
                await asyncio.sleep(base * (2 ** i) + random.random() * 0.1)
            else:
                raise
        except Exception:
            raise

    return ""

async def main():
    parser = argparse.ArgumentParser(description="Analyze images using OpenRouter AI models.")
    parser.add_argument("images", nargs="+", help="Paths to image files.")
    parser.add_argument("--prompt", "-p", required=True, help="Text prompt for analysis.")
    parser.add_argument("--model", "-m", default="qwen/qwen3-vl-8b-instruct", help="OpenRouter model slug.")
    
    args = parser.parse_args()

    try:
        result = await analyze_images(args.images, args.prompt, args.model)
        print(result)
    except Exception as e:
        print(f"Error: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
