#!/usr/bin/env node

// CLI wrapper around shared/camera_path.js
// Reads JSON from stdin: { path, progress: [numbers], options }
// Writes JSON: { cameras: [...] }

const { buildSampler } = require('./camera_path');
const ViewUtils = require('./view_utils');

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (data += chunk));
    process.stdin.on('end', () => resolve(data));
  });
}

async function main() {
  const raw = await readStdin();
  if (!raw) {
    console.error('No input provided to camera_path_cli');
    process.exit(1);
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (err) {
    console.error('Invalid JSON input:', err);
    process.exit(1);
  }

  const pathObj = payload.path || { keyframes: [] };
  const sampler = buildSampler(pathObj);

  let progresses = payload.progress;
  if (!Array.isArray(progresses) && typeof payload.samples === 'number') {
    const steps = Math.max(2, payload.samples);
    progresses = [];
    for (let i = 0; i < steps; i++) {
      progresses.push(i / (steps - 1));
    }
  }
  if (!Array.isArray(progresses)) {
    console.error('Expected "progress" array or "samples" count.');
    process.exit(1);
  }

  const viewport = payload.viewport || { width: 1920, height: 1080 };
  const tileSize = payload.tileSize || 512;

  const cameras = [];
  const uniqueTiles = new Set();

  progresses.forEach((p, idx) => {
    const cam = sampler.cameraAtProgress(p);
    if (cam) {
      cameras.push(cam);
      
      // Calculate tiles using the shared "Single Source of Truth" logic
      const tiles = ViewUtils.getRequiredTiles(cam, viewport.width, viewport.height, tileSize);
      
      tiles.forEach(t => {
        uniqueTiles.add(`${t.level}|${t.x}|${t.y}`);
      });
    }
  });

  // Convert Set back to array of objects
  const allTiles = Array.from(uniqueTiles).map(s => {
    const parts = s.split('|');
    // level is integer, x and y are strings (BigInts)
    return { 
      level: parseInt(parts[0], 10), 
      x: parts[1], 
      y: parts[2] 
    };
  });

  process.stdout.write(JSON.stringify({ cameras, tiles: allTiles }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
