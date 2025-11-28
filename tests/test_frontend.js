/**
 * Frontend logic smoke test executed in a Node.js sandbox (no browser).
 * Verifies zoom math, layer reconciliation, and DOM reuse for tiles.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Helper to load file from project root (since we are running from tests/)
const PROJECT_ROOT = path.join(__dirname, '..');
const MAIN_JS_PATH = path.join(PROJECT_ROOT, 'frontend', 'main.js');

// Mock DOM API
const document = {
    activeElement: null,
    getElementById: (id) => ({
        addEventListener: () => {},
        style: {},
        value: 0,
        textContent: '',
        getBoundingClientRect: () => ({ width: 800, height: 600 }),
        appendChild: (child) => { /* mocked below in layers */ },
        innerHTML: '',
        classList: {
            add: () => {},
            remove: () => {},
            contains: () => false
        }
    }),
    getElementsByName: (name) => [],
    createElement: (tag) => ({
        style: {},
        src: '',
        remove: function() { this._removed = true; },
        _removed: false
    })
};

const window = {
    addEventListener: () => {},
    requestAnimationFrame: (cb) => {}, 
    location: { search: '' }
};

const Image = class {
    constructor() {
        this.style = {};
    }
};

// Load main.js content
if (!fs.existsSync(MAIN_JS_PATH)) {
    console.error(`Error: Could not find ${MAIN_JS_PATH}`);
    process.exit(1);
}

let mainJsContent = fs.readFileSync(MAIN_JS_PATH, 'utf8');

// Expose variables by changing const to var so they attach to the sandbox global scope.
// This allows us to inspect internal state that is not exported.
mainJsContent = mainJsContent.replace('const state =', 'var state =');
mainJsContent = mainJsContent.replace('const els =', 'var els =');
mainJsContent = mainJsContent.replace('const activeTileElements =', 'var activeTileElements =');

// Setup Sandbox Context
const sandbox = {
    document,
    window,
    Image,
    fetch: async () => ({ json: async () => ({ datasets: [] }) }),
    requestAnimationFrame: (cb) => {}, 
    console: { log: console.log, error: console.error },
    parseInt: parseInt,
    parseFloat: parseFloat,
    Math: Math,
    setTimeout: setTimeout,
    Map: Map, 
    performance: { now: () => 0 },
    BASE_DATA_URI: '..'
};

vm.createContext(sandbox);
vm.runInContext(mainJsContent, sandbox);

// Extract internals from sandbox
const { state, activeTileElements } = sandbox;

console.log("=== Frontend Logic Test Suite ===\n");

// Test 1: Zoom Logic
console.log("Test 1: Zoom Logic");
// Reset state
state.camera.globalLevel = 0;

console.log(" -> Action: Zooming in by 0.5...");
sandbox.zoom(0.5);
if (Math.abs(state.camera.globalLevel - 0.5) < 1e-6) {
    console.log(" -> PASS: Global level updated to 0.5.");
} else {
    console.error(` -> FAIL: Global level is ${state.camera.globalLevel}`);
}

console.log(" -> Action: Zooming in by 0.6 (Crossing Level Boundary)...");
sandbox.zoom(0.6); // 0.5 + 0.6 = 1.1
if (Math.abs(state.camera.globalLevel - 1.1) < 0.001) {
    console.log(" -> PASS: Global level advanced to 1.1.");
} else {
    console.error(` -> FAIL: Global level: ${state.camera.globalLevel}`);
}

// Test 2: Reconciliation & Crossfade
console.log("\nTest 2: Rendering & Reconciliation");

// Setup Render State
state.activeDatasetId = 'test_ds';
state.config = { max_level: 4 };
state.viewSize = { width: 800, height: 600 };
state.camera.globalLevel = 0.5; 
state.camera.x = 0.5;
state.camera.y = 0.5;

// Expectation:
// Parent (L0) Opacity: 1.0 (Fixed opacity for background stability)
// Child (L1) Opacity: 0.5 (Fading in)

// Mock els.layers container to capture children
const layersChildren = [];
sandbox.els.layers = {
    appendChild: (child) => layersChildren.push(child),
    innerHTML: '',
    style: {}
};

// Run Render Loop once
sandbox.renderLoop();

console.log(` -> Active Tiles Count: ${activeTileElements.size}`);

let parentTiles = 0;
let childTiles = 0;
let parentOpacityCorrect = true;
let childOpacityCorrect = true;

for (const [key, el] of activeTileElements) {
    const parts = key.split('|');
    const level = parseInt(parts[1]);
    const opacity = parseFloat(el.style.opacity);
    
    if (level === 0) {
        parentTiles++;
        // Updated logic: Parent stays at 1.0
        if (Math.abs(opacity - 1.0) > 0.01) parentOpacityCorrect = false;
    } else if (level === 1) {
        childTiles++;
        if (Math.abs(opacity - 0.5) > 0.01) childOpacityCorrect = false;
    }
}

console.log(` -> Parent Tiles (L0): ${parentTiles}`);
console.log(` -> Child Tiles (L1): ${childTiles}`);

if (parentTiles > 0 && childTiles > 0) console.log(" -> PASS: Both layers generated.");
else console.error(" -> FAIL: Missing layers.");

if (parentOpacityCorrect) console.log(" -> PASS: Parent Opacity is 1.0 (Stable Background).");
else console.error(" -> FAIL: Parent Opacity incorrect (Should be 1.0).");

if (childOpacityCorrect) console.log(" -> PASS: Child Opacity matches fractional level (0.5).");
else console.error(" -> FAIL: Child Opacity incorrect.");

// Test 3: Persistence (No Thrashing)
console.log("\nTest 3: Persistence");
const firstRunSize = activeTileElements.size;
const firstRunElement = activeTileElements.values().next().value;

// Run render again with same state
sandbox.renderLoop();

if (activeTileElements.size === firstRunSize) console.log(" -> PASS: Element count stable after second pass.");
const secondRunElement = activeTileElements.values().next().value;

if (firstRunElement === secondRunElement) console.log(" -> PASS: DOM Elements persisted (Object identity match).");
else console.error(" -> FAIL: DOM Elements were recreated (Thrashing detected).");

console.log("\n=== Tests Complete ===");
