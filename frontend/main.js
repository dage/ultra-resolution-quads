const BASE_DATA_URI = '..';
// Logical tile size for layout; actual image resolution can differ.
const LOGICAL_TILE_SIZE = 256;

// Application State
const state = {
    datasets: [],
    activeDatasetId: null,
    config: null,
    camera: {
        level: 0,
        zoomOffset: 0,
        tileX: 0,
        tileY: 0,
        offsetX: 0.5,
        offsetY: 0.5
    },
    mode: 'explore',
    isDragging: false,
    lastMouse: { x: 0, y: 0 },
    viewSize: { width: 0, height: 0 },
    
    // Path Playback State
    paths: [],
    activePath: null,
    pathPlayback: {
        active: false,
        startTime: 0,
        segmentDurations: [],
        totalDuration: 0
    }
};

// DOM Elements
const els = {
    viewer: document.getElementById('viewer'),
    layers: document.getElementById('layers-container'),
    datasetSelect: document.getElementById('dataset-select'),
    datasetInfo: document.getElementById('dataset-info'),
    inputs: {
        level: document.getElementById('in-level'),
        tileX: document.getElementById('in-tileX'),
        tileY: document.getElementById('in-tileY'),
        offsetX: document.getElementById('in-offsetX'),
        offsetY: document.getElementById('in-offsetY'),
    },
    vals: {
        level: document.getElementById('val-level'),
        tileX: document.getElementById('val-tileX'),
        tileY: document.getElementById('val-tileY'),
        offsetX: document.getElementById('val-offsetX'),
        offsetY: document.getElementById('val-offsetY'),
    },
    modeRadios: document.getElementsByName('mode'),
    pathControls: document.getElementById('path-controls'),
    pathSelect: document.getElementById('path-select'),
    btnPlay: document.getElementById('btn-play'),
    btnPause: document.getElementById('btn-pause')
};

// Initialization
async function init() {
    try {
        const resp = await fetch(`${BASE_DATA_URI}/datasets/index.json`);
        const data = await resp.json();
        state.datasets = data.datasets;
        
        populateDatasetSelect();
        if (state.datasets.length > 0) {
            loadDataset(state.datasets[0].id);
        }
        
        setupEventListeners();
        requestAnimationFrame(renderLoop);
    } catch (e) {
        console.error("Failed to init:", e);
        if (els.datasetInfo) els.datasetInfo.textContent = "Error loading datasets. Check console.";
    }
}

function populateDatasetSelect() {
    els.datasetSelect.innerHTML = '';
    state.datasets.forEach(ds => {
        const opt = document.createElement('option');
        opt.value = ds.id;
        opt.textContent = ds.name;
        els.datasetSelect.appendChild(opt);
    });
}

async function loadDataset(id) {
    state.activeDatasetId = id;
    try {
        // Load Config
        const respConfig = await fetch(`${BASE_DATA_URI}/datasets/${id}/config.json`);
        state.config = await respConfig.json();
        els.datasetInfo.textContent = state.config.name + " (Max Level: " + state.config.max_level + ")";
        
        // Load Paths
        try {
            const respPaths = await fetch(`${BASE_DATA_URI}/datasets/${id}/paths.json`);
            const pathsData = await respPaths.json();
            state.paths = pathsData.paths || [];
            populatePathSelect();
        } catch (e) {
            console.log("No paths found or error loading paths", e);
            state.paths = [];
            populatePathSelect();
        }

        resetCamera();
    } catch (e) {
        console.error("Failed to load dataset config:", e);
    }
}

function populatePathSelect() {
    els.pathSelect.innerHTML = '';
    state.paths.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;
        els.pathSelect.appendChild(opt);
    });
    if (state.paths.length > 0) {
        state.activePath = state.paths[0];
    } else {
        state.activePath = null;
    }

    recalculatePathPlaybackTiming();
}

function resetCamera() {
    state.camera = {
        level: 0,
        zoomOffset: 0,
        tileX: 0,
        tileY: 0,
        offsetX: 0.5,
        offsetY: 0.5
    };
    updateUI();
}

function setupEventListeners() {
    // Dataset Select
    els.datasetSelect.addEventListener('change', (e) => loadDataset(e.target.value));
    
    // Mode Select
    Array.from(els.modeRadios).forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (e.target.checked) {
                state.mode = e.target.value;
                els.pathControls.style.display = state.mode === 'path' ? 'block' : 'none';
            }
        });
    });

    // Path Controls
    els.pathSelect.addEventListener('change', (e) => {
        state.activePath = state.paths.find(p => p.id === e.target.value);
        recalculatePathPlaybackTiming();
    });
    
    els.btnPlay.addEventListener('click', () => {
        if (state.activePath) {
            recalculatePathPlaybackTiming();
            state.pathPlayback.active = true;
            state.pathPlayback.startTime = performance.now(); // Reset start time? 
            // For simple loop, just start.
        }
    });
    
    els.btnPause.addEventListener('click', () => {
        state.pathPlayback.active = false;
    });

    // Mouse Interactions
    els.viewer.addEventListener('mousedown', (e) => {
        state.isDragging = true;
        state.lastMouse = { x: e.clientX, y: e.clientY };
    });
    
    window.addEventListener('mouseup', () => state.isDragging = false);
    
    window.addEventListener('mousemove', (e) => {
        if (!state.isDragging) return;
        if (state.mode !== 'explore') return;
        
        const dx = e.clientX - state.lastMouse.x;
        const dy = e.clientY - state.lastMouse.y;
        state.lastMouse = { x: e.clientX, y: e.clientY };
        
        pan(dx, dy);
    });
    
    els.viewer.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (state.mode !== 'explore') return;
        zoom(-e.deltaY * 0.002); // Zoom factor
    }, { passive: false });
    
    // UI Inputs
    els.inputs.level.addEventListener('input', (e) => { state.camera.level = parseInt(e.target.value); updateUI(); });
    els.inputs.tileX.addEventListener('input', (e) => { state.camera.tileX = parseInt(e.target.value); updateUI(); });
    els.inputs.tileY.addEventListener('input', (e) => { state.camera.tileY = parseInt(e.target.value); updateUI(); });
    
    window.addEventListener('resize', updateViewSize);
    updateViewSize();
}

function updateViewSize() {
    const rect = els.viewer.getBoundingClientRect();
    state.viewSize = { width: rect.width, height: rect.height };
}

// Camera Logic
function pan(dx, dy) {
    const scale = Math.pow(2, state.camera.zoomOffset);
    const tileSizePx = LOGICAL_TILE_SIZE * scale;
    
    const dOffX = -dx / tileSizePx;
    const dOffY = -dy / tileSizePx;
    
    state.camera.offsetX += dOffX;
    state.camera.offsetY += dOffY;
    
    normalizeCamera();
    updateUI();
}

function zoom(amount) {
    state.camera.zoomOffset += amount;
    
    while (state.camera.zoomOffset >= 1.0) {
        state.camera.level++;
        state.camera.zoomOffset -= 1.0;
        
        const fullX = (state.camera.tileX + state.camera.offsetX) * 2;
        const fullY = (state.camera.tileY + state.camera.offsetY) * 2;
        
        state.camera.tileX = Math.floor(fullX);
        state.camera.tileY = Math.floor(fullY);
        state.camera.offsetX = fullX % 1;
        state.camera.offsetY = fullY % 1;
    }
    
    while (state.camera.zoomOffset < 0.0) {
        if (state.camera.level > 0) {
            state.camera.level--;
            state.camera.zoomOffset += 1.0;
            
            const fullX = (state.camera.tileX + state.camera.offsetX) / 2;
            const fullY = (state.camera.tileY + state.camera.offsetY) / 2;
            
            state.camera.tileX = Math.floor(fullX);
            state.camera.tileY = Math.floor(fullY);
            state.camera.offsetX = fullX % 1;
            state.camera.offsetY = fullY % 1;
        } else {
            state.camera.zoomOffset = 0;
        }
    }
    
    updateUI();
}

function normalizeCamera() {
    while (state.camera.offsetX < 0) {
        state.camera.offsetX += 1;
        state.camera.tileX--;
    }
    while (state.camera.offsetX >= 1) {
        state.camera.offsetX -= 1;
        state.camera.tileX++;
    }
    
    while (state.camera.offsetY < 0) {
        state.camera.offsetY += 1;
        state.camera.tileY--;
    }
    while (state.camera.offsetY >= 1) {
        state.camera.offsetY -= 1;
        state.camera.tileY++;
    }
}

function updateUI() {
    if (!els.vals.level) return;
    els.vals.level.textContent = state.camera.level + " (+ " + state.camera.zoomOffset.toFixed(2) + ")";
    els.vals.tileX.textContent = state.camera.tileX;
    els.vals.tileY.textContent = state.camera.tileY;
    els.vals.offsetX.textContent = state.camera.offsetX.toFixed(4);
    els.vals.offsetY.textContent = state.camera.offsetY.toFixed(4);
    
    els.inputs.level.value = state.camera.level;
    els.inputs.tileX.value = state.camera.tileX;
    els.inputs.tileY.value = state.camera.tileY;
    els.inputs.offsetX.value = state.camera.offsetX;
    els.inputs.offsetY.value = state.camera.offsetY;
}

// Path Playback
const PATH_SPEED = {
    translationUnitsPerSecond: 0.05, // Normalized world units per second
    zoomLevelsPerSecond: 1.0, // Camera levels per second
    minSegmentMs: 300
};

function cameraToGlobal(camera) {
    const globalLevel = camera.level + (camera.zoomOffset || 0);
    const factor = 1.0 / Math.pow(2, globalLevel);
    return {
        x: (camera.tileX + camera.offsetX) * factor,
        y: (camera.tileY + camera.offsetY) * factor,
        level: globalLevel
    };
}

function segmentDurationMs(k1, k2) {
    const g1 = cameraToGlobal(k1);
    const g2 = cameraToGlobal(k2);
    const translationDist = Math.hypot(g2.x - g1.x, g2.y - g1.y);
    const translationSeconds = translationDist / PATH_SPEED.translationUnitsPerSecond;
    const zoomDelta = Math.abs(g2.level - g1.level);
    const zoomSeconds = zoomDelta / PATH_SPEED.zoomLevelsPerSecond;
    return Math.max((translationSeconds + zoomSeconds) * 1000, PATH_SPEED.minSegmentMs);
}

function recalculatePathPlaybackTiming() {
    if (!state.activePath || state.activePath.keyframes.length < 2) {
        state.pathPlayback.segmentDurations = [];
        state.pathPlayback.totalDuration = 0;
        return;
    }

    const durations = [];
    for (let i = 0; i < state.activePath.keyframes.length - 1; i++) {
        const k1 = state.activePath.keyframes[i].camera;
        const k2 = state.activePath.keyframes[i + 1].camera;
        durations.push(segmentDurationMs(k1, k2));
    }
    state.pathPlayback.segmentDurations = durations;
    state.pathPlayback.totalDuration = durations.reduce((a, b) => a + b, 0);
}

function updatePathPlayback(now) {
    if (!state.activePath || state.activePath.keyframes.length < 2) return;
    if (!state.pathPlayback.segmentDurations.length || state.pathPlayback.totalDuration <= 0) return;

    let elapsed = now - state.pathPlayback.startTime;
    elapsed = elapsed % state.pathPlayback.totalDuration;

    let segmentIndex = 0;
    let segmentTime = elapsed;
    for (let i = 0; i < state.pathPlayback.segmentDurations.length; i++) {
        const segDuration = state.pathPlayback.segmentDurations[i];
        if (segmentTime < segDuration) {
            segmentIndex = i;
            break;
        }
        segmentTime -= segDuration;
    }

    const duration = state.pathPlayback.segmentDurations[segmentIndex];
    const t = duration > 0 ? (segmentTime / duration) : 0;
    const k1 = state.activePath.keyframes[segmentIndex].camera;
    const k2 = state.activePath.keyframes[segmentIndex + 1].camera;

    interpolateCamera(k1, k2, t);
}

function interpolateCamera(k1, k2, t) {
    // Interpolate Level
    // We interpolate "Global Level" = level + zoomOffset
    const gl1 = k1.level + (k1.zoomOffset || 0); // k1.zoomOffset might be undefined if not in json? PRD says offsetX/Y, level.
    // PRD json example: "level": 0, "tileX": 0... "offsetX": 0.5...
    // Wait, PRD example doesn't show zoomOffset in keyframe.
    // It says "camera": { "level": 0, ... }
    // Assuming implicit zoomOffset 0 if not present? 
    // Or maybe level is float in keyframe? PRD says "level" (integer).
    
    // I'll assume k1.level is integer.
    // So Global Level L1 = k1.level.
    // L2 = k2.level.
    const L1 = k1.level;
    const L2 = k2.level;
    
    const Lt = L1 + (L2 - L1) * t;
    
    state.camera.level = Math.floor(Lt);
    state.camera.zoomOffset = Lt - state.camera.level;
    
    // Interpolate Position (Global Coordinates)
    // Pos = (tile + offset) / 2^level
    
    const factor1 = 1.0 / Math.pow(2, L1);
    const gx1 = (k1.tileX + k1.offsetX) * factor1;
    const gy1 = (k1.tileY + k1.offsetY) * factor1;
    
    const factor2 = 1.0 / Math.pow(2, L2);
    const gx2 = (k2.tileX + k2.offsetX) * factor2;
    const gy2 = (k2.tileY + k2.offsetY) * factor2;
    
    const gxt = gx1 + (gx2 - gx1) * t;
    const gyt = gy1 + (gy2 - gy1) * t;
    
    // Convert back to local
    const factorT = Math.pow(2, state.camera.level); // Base level scale
    const fullX = gxt * factorT;
    const fullY = gyt * factorT;
    
    state.camera.tileX = Math.floor(fullX);
    state.camera.tileY = Math.floor(fullY);
    state.camera.offsetX = fullX % 1;
    state.camera.offsetY = fullY % 1;
    
    updateUI();
}

// Rendering
const tileCache = {}; 
const activeTileElements = new Map(); // Key: "level|x|y", Value: DOM Element

function getTileImage(datasetId, level, x, y) {
    // We just return a new image element source, but we don't manage caching logic here 
    // as complexly as before since we rely on the DOM element persistence.
    // But to avoid re-downloading if we just removed it, we can keep the src string or let browser cache handle it.
    // Browser cache is usually sufficient for 'src'.
    const img = document.createElement('img');
    img.src = `${BASE_DATA_URI}/datasets/${datasetId}/tiles/${level}/${x}/${y}.png`;
    img.className = 'tile';
    img.style.width = `${LOGICAL_TILE_SIZE}px`;
    img.style.height = `${LOGICAL_TILE_SIZE}px`;
    img.onerror = () => { img.style.display = 'none'; };
    return img;
}

function updateLayer(level, opacity, targetTiles) {
    if (opacity <= 0.001) return;

    const tileSize = LOGICAL_TILE_SIZE;

    const camX_C = state.camera.tileX + state.camera.offsetX;
    const camY_C = state.camera.tileY + state.camera.offsetY;
    
    const factor = Math.pow(2, level - state.camera.level);
    const camX_T = camX_C * factor;
    const camY_T = camY_C * factor;
    
    const displayScale = Math.pow(2, state.camera.level + state.camera.zoomOffset - level);
    const tileSizeOnScreen = tileSize * displayScale;
    
    const tilesInViewX = state.viewSize.width / tileSizeOnScreen;
    const tilesInViewY = state.viewSize.height / tileSizeOnScreen;
    
    // Add a bit of margin to avoid popping
    const margin = 1;
    const minTileX = Math.floor(camX_T - tilesInViewX / 2 - margin);
    const maxTileX = Math.floor(camX_T + tilesInViewX / 2 + margin);
    const minTileY = Math.floor(camY_T - tilesInViewY / 2 - margin);
    const maxTileY = Math.floor(camY_T + tilesInViewY / 2 + margin);
    
    const limit = Math.pow(2, level);
    
    for (let x = minTileX; x <= maxTileX; x++) {
        for (let y = minTileY; y <= maxTileY; y++) {
            if (x < 0 || y < 0 || x >= limit || y >= limit) continue;
            
            const key = `${state.activeDatasetId}|${level}|${x}|${y}`;
            const distX = x - camX_T;
            const distY = y - camY_T;
            
            const screenX = state.viewSize.width/2 + distX * tileSizeOnScreen;
            const screenY = state.viewSize.height/2 + distY * tileSizeOnScreen;
            
            targetTiles.set(key, {
                datasetId: state.activeDatasetId,
                level, x, y,
                tx: screenX,
                ty: screenY,
                scale: displayScale,
                opacity: opacity,
                zIndex: level
            });
        }
    }
}

function renderLoop() {
    if (state.mode === 'path' && state.pathPlayback.active) {
        updatePathPlayback(performance.now());
    }

    if (!state.activeDatasetId || !state.config) {
        requestAnimationFrame(renderLoop);
        return;
    }
    
    // Calculate all tiles that SHOULD be visible
    const targetTiles = new Map();
    
    // Base stack: keep all coarser levels fully opaque as a stable background.
    // We only fade in additional detail layers above the current camera level.
    for (let level = 0; level <= state.camera.level; level++) {
        updateLayer(level, 1.0, targetTiles);
    }
    
    // Child layer (fade in) above the current level.
    if (state.camera.level < state.config.max_level) {
        const childOpacity = state.camera.zoomOffset;
        updateLayer(state.camera.level + 1, childOpacity, targetTiles);
    }
    
    // Reconciliation
    
    // 1. Remove tiles not in target
    for (const [key, el] of activeTileElements) {
        if (!targetTiles.has(key)) {
            el.remove();
            activeTileElements.delete(key);
        }
    }
    
    // 2. Add or Update tiles
    for (const [key, props] of targetTiles) {
        let el = activeTileElements.get(key);
        if (!el) {
            el = getTileImage(props.datasetId, props.level, props.x, props.y);
            els.layers.appendChild(el);
            activeTileElements.set(key, el);
        }
        
        // Update styles: position via translate, scale via transform.
        // We avoid rounding here to prevent per-tile rounding differences
        // from introducing tiny seams between tiles.
        el.style.transform = `translate(${props.tx}px, ${props.ty}px) scale(${props.scale})`;
        el.style.transformOrigin = 'top left';
        el.style.opacity = props.opacity.toFixed(3);
        el.style.zIndex = props.zIndex;
    }
    
    requestAnimationFrame(renderLoop);
}

init();
