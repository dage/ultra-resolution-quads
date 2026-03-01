#!/usr/bin/env python3
"""
Batch analyze all procedural textures using the analyze_image tool.
"""

import os
import json
import glob
from pathlib import Path
import subprocess
import sys

def analyze_texture(image_path, prompt):
    """Analyze a single texture using the analyze_image tool."""
    try:
        result = subprocess.run([
            sys.executable, 'backend/tools/analyze_image.py',
            image_path, '--prompt', prompt
        ], capture_output=True, text=True, cwd=os.path.dirname(__file__))

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Analysis failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Analysis error: {str(e)}"

def main():
    texture_dir = "artifacts/procedural_textures_v1"
    output_file = "artifacts/procedural_textures_v1/analysis_results.json"

    if not os.path.exists(texture_dir):
        print(f"Texture directory {texture_dir} not found!")
        return

    # Find all PNG files
    texture_files = glob.glob(os.path.join(texture_dir, "*.png"))
    texture_files.sort()

    print(f"Found {len(texture_files)} textures to analyze")

    analysis_prompt = """
Analyze this procedural texture/material generated using advanced hash-based techniques.
Describe in detail:
1. Visual characteristics, patterns, and aesthetic qualities
2. Technical quality (artifacts, consistency, complexity, procedural nature)
3. Potential applications and use cases in computer graphics/materials
4. Strengths and unique features
5. Areas for improvement or refinement
6. How well it demonstrates the concepts of hash-based procedural generation
"""

    results = {}

    for i, texture_path in enumerate(texture_files):
        filename = os.path.basename(texture_path)
        print(f"Analyzing {i+1}/{len(texture_files)}: {filename}")

        analysis = analyze_texture(texture_path, analysis_prompt)
        results[filename] = analysis

        # Save progress every 5 textures
        if (i + 1) % 5 == 0:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Progress saved ({i+1}/{len(texture_files)})")

    # Final save
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Analysis complete! Results saved to {output_file}")

    # Print summary
    print("\nAnalysis Summary:")
    texture_types = {}
    for filename in results.keys():
        texture_type = filename.split('_v')[0]
        texture_types[texture_type] = texture_types.get(texture_type, 0) + 1

    for texture_type, count in texture_types.items():
        print(f"- {texture_type}: {count} variants")

if __name__ == "__main__":
    main()



