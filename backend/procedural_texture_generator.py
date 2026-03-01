# backend/procedural_texture_generator.py
"""
Advanced Hash-Based Procedural Generation of Abstract Textures and Materials

This script implements various procedural generation techniques for creating
abstract textures and materials using hash-based approaches, as described in
the research on GPU hash functions, noise algorithms, and material synthesis.
"""

import os
import sys
import numpy as np
import random
from typing import Tuple, List, Optional, Dict, Any
from PIL import Image, ImageFilter
import math
import hashlib
from pathlib import Path
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class HashFunctions:
    """Collection of hash functions optimized for procedural generation."""

    @staticmethod
    def pcg_hash(x: int, y: int, seed: int = 0) -> float:
        """Permuted Congruential Generator - high quality, statistical properties."""
        # PCG hash for 2D coordinates
        state = (x * 73856093) ^ (y * 19349663) ^ seed
        state = (state ^ (state >> 13)) * 0x9e3779b9
        state = state ^ (state >> 16)
        return (state & 0x7FFFFFFF) / 0x7FFFFFFF  # Normalize to [0,1)

    @staticmethod
    def jenkins_hash(x: int, y: int, seed: int = 0) -> float:
        """Jenkins one-at-a-time hash - good balance of speed and quality."""
        hash_val = seed
        hash_val += x
        hash_val += (hash_val << 10)
        hash_val ^= (hash_val >> 6)
        hash_val += y
        hash_val += (hash_val << 10)
        hash_val ^= (hash_val >> 6)
        hash_val += (hash_val << 3)
        hash_val ^= (hash_val >> 11)
        hash_val += (hash_val << 15)
        return (hash_val & 0x7FFFFFFF) / 0x7FFFFFFF

    @staticmethod
    def xxhash_style(x: int, y: int, seed: int = 0) -> float:
        """xxHash-inspired integer hash - fast and high quality."""
        # Simplified xxHash-style mixing
        h = seed + 0x9e3779b9 + 8  # xxHash constants
        h ^= (x << 5) + y
        h = ((h << 13) | (h >> 19)) * 0x9e3779b9
        h ^= h >> 15
        return (h & 0x7FFFFFFF) / 0x7FFFFFFF


class NoiseGenerators:
    """Various noise generation algorithms."""

    def __init__(self, hash_func='pcg'):
        self.hash_func = hash_func
        self.hash_impl = {
            'pcg': HashFunctions.pcg_hash,
            'jenkins': HashFunctions.jenkins_hash,
            'xxhash': HashFunctions.xxhash_style
        }[hash_func]

    def value_noise(self, x: float, y: float, seed: int = 0) -> float:
        """Value noise - assigns random values to lattice points."""
        # Get lattice coordinates
        ix, iy = int(x), int(y)
        fx, fy = x - ix, y - iy

        # Get corner values
        n00 = self.hash_impl(ix, iy, seed)
        n10 = self.hash_impl(ix+1, iy, seed)
        n01 = self.hash_impl(ix, iy+1, seed)
        n11 = self.hash_impl(ix+1, iy+1, seed)

        # Smooth interpolation
        u = self.smooth_step(fx)
        v = self.smooth_step(fy)

        # Bilinear interpolation
        return self.lerp(self.lerp(n00, n10, u), self.lerp(n01, n11, u), v)

    def gradient_noise(self, x: float, y: float, seed: int = 0) -> float:
        """Gradient (Perlin-style) noise."""
        ix, iy = int(x), int(y)
        fx, fy = x - ix, y - iy

        # Get gradients at corners
        g00 = self._random_gradient(ix, iy, seed)
        g10 = self._random_gradient(ix+1, iy, seed)
        g01 = self._random_gradient(ix, iy+1, seed)
        g11 = self._random_gradient(ix+1, iy+1, seed)

        # Distance vectors
        d00 = (fx, fy)
        d10 = (fx-1, fy)
        d01 = (fx, fy-1)
        d11 = (fx-1, fy-1)

        # Dot products
        n00 = np.dot(g00, d00)
        n10 = np.dot(g10, d10)
        n01 = np.dot(g01, d01)
        n11 = np.dot(g11, d11)

        # Smooth interpolation
        u = self.smooth_step(fx)
        v = self.smooth_step(fy)

        return self.lerp(self.lerp(n00, n10, u), self.lerp(n01, n11, u), v)

    def simplex_noise(self, x: float, y: float, seed: int = 0) -> float:
        """Simplified 2D Simplex noise."""
        # Simplex noise implementation
        F2 = 0.3660254037844386  # (sqrt(3)-1)/2
        G2 = 0.21132486540518713  # (3-sqrt(3))/6

        s = (x + y) * F2
        i = int(x + s)
        j = int(y + s)

        t = (i + j) * G2
        X0 = i - t
        Y0 = j - t
        x0 = x - X0
        y0 = y - Y0

        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1

        x1 = x0 - i1 + G2
        y1 = y0 - j1 + G2
        x2 = x0 - 1.0 + 2.0 * G2
        y2 = y0 - 1.0 + 2.0 * G2

        # Hash gradients
        gi0 = self._random_gradient(i, j, seed)
        gi1 = self._random_gradient(i+i1, j+j1, seed)
        gi2 = self._random_gradient(i+1, j+1, seed)

        # Noise contributions
        n0 = self._simplex_contrib(x0, y0, gi0)
        n1 = self._simplex_contrib(x1, y1, gi1)
        n2 = self._simplex_contrib(x2, y2, gi2)

        return 70.0 * (n0 + n1 + n2)  # Scale to roughly match Perlin

    def _simplex_contrib(self, x: float, y: float, g: Tuple[float, float]) -> float:
        """Simplex noise contribution function."""
        t = 0.5 - x*x - y*y
        if t < 0:
            return 0
        t *= t
        return t * t * np.dot(g, (x, y))

    def _random_gradient(self, x: int, y: int, seed: int) -> Tuple[float, float]:
        """Generate pseudo-random gradient vector."""
        h = int(self.hash_impl(x, y, seed) * 8)
        gradients = [
            (1,0), (-1,0), (0,1), (0,-1),
            (1,1), (-1,1), (1,-1), (-1,-1)
        ]
        return gradients[h % 8]

    def gabor_noise(self, x: float, y: float, frequency: float = 0.1,
                   orientation: float = 0.0, bandwidth: float = 1.0,
                   seed: int = 0) -> float:
        """Gabor noise - anisotropic, frequency-controlled noise."""
        # Gabor kernel parameters
        K = 1.0 / (2.0 * np.pi * bandwidth**2)
        a = 1.0 / bandwidth

        # Rotate coordinates
        cos_theta = np.cos(orientation)
        sin_theta = np.sin(orientation)
        xr = x * cos_theta - y * sin_theta
        yr = x * sin_theta + y * cos_theta

        # Gabor kernel
        envelope = K * np.exp(-np.pi * a**2 * (xr**2 + yr**2))
        carrier = np.cos(2 * np.pi * frequency * xr)

        # Add some randomness via hash
        phase_offset = self.hash_impl(int(x*10), int(y*10), seed) * 2 * np.pi
        carrier = np.cos(2 * np.pi * frequency * xr + phase_offset)

        return envelope * carrier

    @staticmethod
    def smooth_step(t: float) -> float:
        """Smooth step interpolation."""
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def lerp(a: float, b: float, t: float) -> float:
        """Linear interpolation."""
        return a + t * (b - a)

    def fbm(self, x: float, y: float, octaves: int = 6, lacunarity: float = 2.0,
           persistence: float = 0.5, seed: int = 0, noise_type: str = 'gradient') -> float:
        """Fractional Brownian Motion."""
        value = 0.0
        amplitude = 1.0
        frequency = 1.0

        for i in range(octaves):
            if noise_type == 'gradient':
                value += amplitude * self.gradient_noise(x * frequency, y * frequency, seed + i)
            elif noise_type == 'value':
                value += amplitude * self.value_noise(x * frequency, y * frequency, seed + i)
            elif noise_type == 'simplex':
                value += amplitude * self.simplex_noise(x * frequency, y * frequency, seed + i)
            elif noise_type == 'gabor':
                value += amplitude * self.gabor_noise(x * frequency, y * frequency,
                                                     frequency/10.0, 0.0, 1.0, seed + i)

            amplitude *= persistence
            frequency *= lacunarity

        return value

    def domain_warping(self, x: float, y: float, intensity: float = 1.0, seed: int = 0) -> float:
        """Domain warping for complex patterns."""
        # Simple domain warping
        warp1 = self.fbm(x, y, 4, 2.0, 0.5, seed) * intensity
        warp2 = self.fbm(x + warp1, y + warp1, 4, 2.0, 0.5, seed + 1) * intensity

        return self.fbm(x + warp2, y + warp2, 6, 2.0, 0.5, seed + 2)


class ProceduralTextures:
    """High-level procedural texture generators."""

    def __init__(self, width: int = 512, height: int = 512):
        self.width = width
        self.height = height
        self.noise_gen = NoiseGenerators('pcg')

    def generate_texture(self, texture_type: str, **params) -> Image.Image:
        """Generate a procedural texture."""
        if texture_type == 'marble':
            return self._generate_marble(**params)
        elif texture_type == 'wood':
            return self._generate_wood(**params)
        elif texture_type == 'stone':
            return self._generate_stone(**params)
        elif texture_type == 'cloud':
            return self._generate_cloud(**params)
        elif texture_type == 'fire':
            return self._generate_fire(**params)
        elif texture_type == 'abstract_flow':
            return self._generate_abstract_flow(**params)
        elif texture_type == 'crystalline':
            return self._generate_crystalline(**params)
        elif texture_type == 'organic_tissue':
            return self._generate_organic_tissue(**params)
        elif texture_type == 'metallic_surface':
            return self._generate_metallic_surface(**params)
        elif texture_type == 'gabor_pattern':
            return self._generate_gabor_pattern(**params)
        else:
            raise ValueError(f"Unknown texture type: {texture_type}")

    def _generate_marble(self, seed: int = 0) -> Image.Image:
        """Generate marble texture using domain warping."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                # Normalized coordinates
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                # Domain warping for marble veins
                warp = self.noise_gen.domain_warping(nx, ny, 2.0, seed)

                # Marble pattern
                marble = np.sin(nx * 10.0 + warp * 5.0) * 0.5 + 0.5

                # Color marble
                r = int((0.8 + marble * 0.2) * 255)
                g = int((0.9 + marble * 0.1) * 255)
                b = int((0.95 + marble * 0.05) * 255)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_wood(self, seed: int = 0) -> Image.Image:
        """Generate wood texture with rings and grain."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 8.0 - 4.0
                ny = y / self.height * 8.0 - 4.0

                # Distance from center (creates rings)
                dist = np.sqrt(nx**2 + ny**2)

                # Wood rings
                rings = np.sin(dist * 15.0) * 0.5 + 0.5

                # Add some grain variation
                grain = self.noise_gen.fbm(nx * 50.0, ny * 50.0, 3, 2.0, 0.3, seed) * 0.1

                wood = rings + grain
                wood = np.clip(wood, 0.0, 1.0)

                # Wood colors (light to dark brown)
                r = int((0.6 + wood * 0.4) * 255)
                g = int((0.3 + wood * 0.4) * 255)
                b = int((0.1 + wood * 0.3) * 255)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_stone(self, seed: int = 0) -> Image.Image:
        """Generate stone texture with crystalline structure."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 6.0
                ny = y / self.height * 6.0

                # Multi-octave fBm for stone texture
                stone = self.noise_gen.fbm(nx, ny, 8, 2.2, 0.4, seed, 'gradient')

                # Add some crystalline variation
                crystal = self.noise_gen.fbm(nx * 20.0, ny * 20.0, 3, 1.8, 0.6, seed + 1, 'value') * 0.3

                stone = stone + crystal
                stone = np.clip(stone * 0.5 + 0.5, 0.0, 1.0)

                # Stone colors (gray variations)
                gray = int(stone * 255)
                r = gray + random.randint(-20, 20)
                g = gray + random.randint(-20, 20)
                b = gray + random.randint(-20, 20)

                r = np.clip(r, 50, 200)
                g = np.clip(g, 50, 200)
                b = np.clip(b, 50, 200)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_cloud(self, seed: int = 0) -> Image.Image:
        """Generate cloud texture."""
        img = Image.new('RGBA', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                # Cloud density using fBm
                density = self.noise_gen.fbm(nx, ny, 6, 2.0, 0.5, seed, 'simplex')
                density = (density * 0.5 + 0.5) ** 2  # Make denser

                # Cloud color (white with some blue tint)
                alpha = int(density * 255)
                r = int(255 - density * 30)
                g = int(255 - density * 20)
                b = 255

                pixels.append((r, g, b, alpha))

        img.putdata(pixels)
        return img

    def _generate_fire(self, seed: int = 0) -> Image.Image:
        """Generate fire texture with turbulent motion."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 2.0
                ny = (self.height - y) / self.height * 4.0  # Flames rise upward

                # Turbulent fire using domain warping
                fire = self.noise_gen.domain_warping(nx, ny, 1.5, seed)

                # Add some high-frequency detail
                detail = self.noise_gen.fbm(nx * 20.0, ny * 20.0, 2, 2.0, 0.3, seed + 1) * 0.2

                fire = fire + detail
                fire = np.sin(fire * 8.0) * 0.5 + 0.5

                # Fire colors (red to yellow to white)
                if fire < 0.3:
                    r, g, b = 255, int(fire * 255 / 0.3), 0
                elif fire < 0.7:
                    r = 255
                    g = 255
                    b = int((fire - 0.3) * 255 / 0.4)
                else:
                    intensity = int((fire - 0.7) * 255 / 0.3)
                    r = g = b = intensity

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_abstract_flow(self, seed: int = 0) -> Image.Image:
        """Generate abstract flowing patterns."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 6.0
                ny = y / self.height * 6.0

                # Complex domain warping
                flow1 = self.noise_gen.domain_warping(nx, ny, 3.0, seed)
                flow2 = self.noise_gen.domain_warping(nx + flow1, ny + flow1, 2.0, seed + 1)

                # Combine different noise types
                pattern = (flow1 * 0.6 + flow2 * 0.4)

                # Color mapping using trigonometric functions
                hue = (np.sin(pattern * 4.0) + 1.0) * 0.5
                sat = (np.cos(pattern * 6.0) + 1.0) * 0.5

                r = int(hue * 255)
                g = int(sat * 255)
                b = int((1.0 - hue) * sat * 255)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_crystalline(self, seed: int = 0) -> Image.Image:
        """Generate crystalline/ice texture."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 8.0
                ny = y / self.height * 8.0

                # Voronoi-like crystalline structure
                crystal = self.noise_gen.fbm(nx, ny, 5, 1.5, 0.7, seed, 'value')

                # Add sharp crystalline edges
                sharp = np.abs(np.sin(crystal * 20.0))

                # Ice-like colors
                intensity = crystal * 0.8 + sharp * 0.2
                intensity = np.clip(intensity, 0.0, 1.0)

                r = int(200 + intensity * 55)
                g = int(220 + intensity * 35)
                b = int(255)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_organic_tissue(self, seed: int = 0) -> Image.Image:
        """Generate organic tissue-like texture."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 5.0
                ny = y / self.height * 5.0

                # Organic cell-like structures
                cell1 = self.noise_gen.fbm(nx, ny, 4, 2.5, 0.4, seed)
                cell2 = self.noise_gen.fbm(nx * 1.5, ny * 1.5, 3, 2.0, 0.6, seed + 1)

                tissue = (cell1 + cell2 * 0.5) * 0.5 + 0.5

                # Add some vein-like structures
                veins = np.abs(np.sin(nx * 15.0 + cell1 * 5.0)) * 0.1

                tissue += veins
                tissue = np.clip(tissue, 0.0, 1.0)

                # Organic colors (pinkish flesh tones)
                r = int(180 + tissue * 75)
                g = int(120 + tissue * 60)
                b = int(140 + tissue * 40)

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_metallic_surface(self, seed: int = 0) -> Image.Image:
        """Generate metallic surface with reflections."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 10.0
                ny = y / self.height * 10.0

                # Metallic surface with scratches and reflections
                base = self.noise_gen.fbm(nx, ny, 3, 2.0, 0.5, seed)

                # Add high-frequency scratches
                scratches = self.noise_gen.fbm(nx * 50.0, ny * 50.0, 2, 1.5, 0.8, seed + 1) * 0.3

                # Metallic sheen
                sheen = np.abs(np.sin(nx * 20.0 + ny * 20.0 + base * 10.0)) * 0.2

                metal = base + scratches + sheen
                metal = np.clip(metal, 0.0, 1.0)

                # Metallic colors (chrome-like)
                if metal < 0.4:
                    r = g = b = int(metal * 255 / 0.4)
                else:
                    intensity = int(255 - (metal - 0.4) * 255 / 0.6)
                    r = g = b = intensity

                pixels.append((r, g, b))

        img.putdata(pixels)
        return img

    def _generate_gabor_pattern(self, seed: int = 0) -> Image.Image:
        """Generate Gabor noise pattern."""
        img = Image.new('RGB', (self.width, self.height))
        pixels = []

        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 10.0
                ny = y / self.height * 10.0

                # Multiple Gabor kernels with different orientations
                gabor1 = self.noise_gen.gabor_noise(nx, ny, 2.0, 0.0, 1.0, seed)
                gabor2 = self.noise_gen.gabor_noise(nx, ny, 2.0, np.pi/4, 1.0, seed + 1)
                gabor3 = self.noise_gen.gabor_noise(nx, ny, 2.0, np.pi/2, 1.0, seed + 2)

                pattern = (gabor1 + gabor2 + gabor3) * 0.33
                pattern = pattern * 0.5 + 0.5  # Normalize

                # Color based on pattern intensity
                intensity = int(pattern * 255)
                pixels.append((intensity, intensity, intensity))

        img.putdata(pixels)
        return img

    def generate_pbr_material(self, albedo_seed: int = 0, normal_seed: int = 1,
                           roughness_seed: int = 2, metallic_seed: int = 3) -> Dict[str, Image.Image]:
        """Generate a complete PBR material set."""
        materials = {}

        # Albedo map
        img = Image.new('RGB', (self.width, self.height))
        pixels = []
        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                # Complex albedo pattern
                pattern = self.noise_gen.domain_warping(nx, ny, 1.0, albedo_seed)
                pattern = (pattern + 1.0) * 0.5

                # Color harmony (triangular color mixing)
                r = int(pattern * 255)
                g = int((1.0 - pattern) * 200 + pattern * 100)
                b = int(pattern * 150 + (1.0 - pattern) * 255)

                pixels.append((r, g, b))
        img.putdata(pixels)
        materials['albedo'] = img

        # Normal map (using finite differences)
        img = Image.new('RGB', (self.width, self.height))
        pixels = []
        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                # Height field for normal calculation
                h = self.noise_gen.fbm(nx, ny, 4, 2.0, 0.5, normal_seed)

                # Finite differences for normal
                eps = 0.01
                dhdx = (self.noise_gen.fbm(nx + eps, ny, 4, 2.0, 0.5, normal_seed) - h) / eps
                dhdy = (self.noise_gen.fbm(nx, ny + eps, 4, 2.0, 0.5, normal_seed) - h) / eps

                # Normal vector
                nx_norm = -dhdx
                ny_norm = -dhdy
                nz_norm = 1.0

                # Normalize
                length = np.sqrt(nx_norm**2 + ny_norm**2 + nz_norm**2)
                nx_norm /= length
                ny_norm /= length
                nz_norm /= length

                # Convert to RGB (0-255 range)
                r = int((nx_norm + 1.0) * 0.5 * 255)
                g = int((ny_norm + 1.0) * 0.5 * 255)
                b = int((nz_norm + 1.0) * 0.5 * 255)

                pixels.append((r, g, b))
        img.putdata(pixels)
        materials['normal'] = img

        # Roughness map
        img = Image.new('L', (self.width, self.height))
        pixels = []
        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                roughness = self.noise_gen.fbm(nx, ny, 3, 2.0, 0.5, roughness_seed)
                roughness = (roughness + 1.0) * 0.5  # [0,1]
                pixels.append(int(roughness * 255))
        img.putdata(pixels)
        materials['roughness'] = img

        # Metallic map
        img = Image.new('L', (self.width, self.height))
        pixels = []
        for y in range(self.height):
            for x in range(self.width):
                nx = x / self.width * 4.0
                ny = y / self.height * 4.0

                metallic = self.noise_gen.fbm(nx * 2.0, ny * 2.0, 2, 1.5, 0.7, metallic_seed)
                metallic = (metallic + 1.0) * 0.5
                metallic = np.where(metallic > 0.6, 1.0, 0.0)  # Binary metallic
                pixels.append(int(metallic * 255))
        img.putdata(pixels)
        materials['metallic'] = img

        return materials


def generate_procedural_collection(output_dir: str = "artifacts/procedural_textures",
                                 image_size: int = 512) -> List[str]:
    """Generate a collection of procedural textures."""
    os.makedirs(output_dir, exist_ok=True)

    generator = ProceduralTextures(image_size, image_size)
    generated_files = []

    # Texture types to generate
    texture_types = [
        'marble', 'wood', 'stone', 'cloud', 'fire', 'abstract_flow',
        'crystalline', 'organic_tissue', 'metallic_surface', 'gabor_pattern'
    ]

    # Generate multiple variations of each texture type
    for texture_type in texture_types:
        for variant in range(3):  # 3 variations per type
            seed = hash(f"{texture_type}_{variant}") % 10000
            try:
                img = generator.generate_texture(texture_type, seed=seed)
                filename = f"{texture_type}_v{variant+1}.png"
                filepath = os.path.join(output_dir, filename)
                img.save(filepath)
                generated_files.append(filepath)
                print(f"Generated: {filename}")
            except Exception as e:
                print(f"Error generating {texture_type}_v{variant+1}: {e}")

    # Generate PBR material sets
    for material_id in range(5):
        try:
            materials = generator.generate_pbr_material(
                albedo_seed=material_id * 4,
                normal_seed=material_id * 4 + 1,
                roughness_seed=material_id * 4 + 2,
                metallic_seed=material_id * 4 + 3
            )

            for mat_type, img in materials.items():
                filename = f"pbr_material_{material_id+1}_{mat_type}.png"
                filepath = os.path.join(output_dir, filename)
                img.save(filepath)
                generated_files.append(filepath)
                print(f"Generated: {filename}")
        except Exception as e:
            print(f"Error generating PBR material {material_id+1}: {e}")

    return generated_files


def analyze_collection(image_paths: List[str], analysis_prompt: str) -> Dict[str, Any]:
    """Analyze the generated texture collection."""
    from backend.tools.analyze_image import analyze_images

    results = {}
    for i, img_path in enumerate(image_paths):
        try:
            analysis = analyze_images([img_path], analysis_prompt)
            results[os.path.basename(img_path)] = analysis
            print(f"Analyzed {os.path.basename(img_path)}")
        except Exception as e:
            print(f"Error analyzing {os.path.basename(img_path)}: {e}")
            results[os.path.basename(img_path)] = f"Analysis failed: {e}"

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate procedural textures using advanced hash-based techniques")
    parser.add_argument("--output_dir", default="artifacts/procedural_textures",
                       help="Output directory for generated textures")
    parser.add_argument("--size", type=int, default=512,
                       help="Size of generated textures (width x height)")
    parser.add_argument("--analyze", action="store_true",
                       help="Analyze generated textures using AI")
    parser.add_argument("--analysis_prompt", default="""
Analyze this procedural texture/material. Describe:
1. Visual characteristics and patterns
2. Technical quality (artifacts, consistency, complexity)
3. Potential use cases and applications
4. Strengths and weaknesses
5. Suggestions for improvement
""", help="Prompt for texture analysis")

    args = parser.parse_args()

    print("Generating procedural texture collection...")
    generated_files = generate_procedural_collection(args.output_dir, args.size)

    if args.analyze:
        print("\nAnalyzing generated textures...")
        analysis_results = analyze_collection(generated_files, args.analysis_prompt)

        # Save analysis results
        analysis_file = os.path.join(args.output_dir, "analysis_results.json")
        with open(analysis_file, 'w') as f:
            json.dump(analysis_results, f, indent=2)
        print(f"Analysis results saved to: {analysis_file}")

    print(f"\nGenerated {len(generated_files)} textures in {args.output_dir}")
