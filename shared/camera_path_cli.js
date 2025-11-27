#!/usr/bin/env node

// CLI wrapper around shared/camera_path.js
// Reads JSON from stdin: { path, progress: [numbers], options }
// Writes JSON: { cameras: [...] }

const { buildSampler } = require('./camera_path');

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
  const options = payload.options || {};
  const sampler = buildSampler(pathObj, options);

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

  const cameras = progresses.map((p) => sampler.cameraAtProgress(p));
  process.stdout.write(JSON.stringify({ cameras }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
