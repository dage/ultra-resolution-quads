const BASE_DATA_URI = '..';
// Logical tile size for layout; actual image resolution can differ.
const LOGICAL_TILE_SIZE = 512;

// Application State
const state = {
    datasets: [],
    activeDatasetId: null,
    config: null,
    camera: {
        globalLevel: 0,
        x: 0.5,
        y: 0.5
    },
    mode: 'explore',
    isDragging: false,
    lastMouse: { x: 0, y: 0 },
    viewSize: { width: 0, height: 0 },
    
    // Path Playback State
    paths: [],
    activePath: null,
    pathSampler: null,
    pathPlayback: {
        active: false,
        startTime: 0,
        currentElapsed: 0,
        segmentDurations: [],
        totalDuration: 0
    }
};

// DOM Elements
const els = {
    viewer: document.getElementById('viewer'),
    layers: document.getElementById('layers-container'),
    datasetSelect: document.getElementById('dataset-select'),
    inputs: {
        level: document.getElementById('in-level'),
        x: document.getElementById('in-x'),
        y: document.getElementById('in-y'),
        time: document.getElementById('in-time'),
    },
    vals: {
        level: document.getElementById('val-level'),
        x: document.getElementById('val-x'),
        y: document.getElementById('val-y'),
    },
    modeRadios: document.getElementsByName('mode'),
    pathControls: document.getElementById('path-controls'),
    btnReset: document.getElementById('btn-reset'),
    btns: {
        start: document.getElementById('btn-skip-start'),
        back: document.getElementById('btn-skip-back'),
        playPause: document.getElementById('btn-play-pause'),
        fwd: document.getElementById('btn-skip-fwd'),
        end: document.getElementById('btn-skip-end')
    }
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
        
        // Load Paths
        try {
            const respPaths = await fetch(`${BASE_DATA_URI}/datasets/${id}/paths.json`);
            const pathsData = await respPaths.json();
            state.paths = pathsData.paths || [];
            autoSelectPath();
        } catch (e) {
            console.log("No paths found or error loading paths", e);
            state.paths = [];
            autoSelectPath();
        }

        resetCamera();
    } catch (e) {
        console.error("Failed to load dataset config:", e);
    }
}

function setActivePath(path) {
    const resolved = (typeof CameraPath !== 'undefined' && CameraPath.resolvePathMacros)
        ? CameraPath.resolvePathMacros(path || {})
        : (path || null);

    state.activePath = resolved;
    if (!resolved) {
        state.pathSampler = null;
        return;
    }
    if (typeof CameraPath === 'undefined') {
        console.error('CameraPath module not loaded');
        state.pathSampler = null;
        return;
    }
    state.pathSampler = CameraPath.buildSampler(resolved, { tension: 0.0, resolution: 2000 });
}

function autoSelectPath() {
    // Automatically select the first path if available
    if (state.paths.length > 0) {
        setActivePath(state.paths[0]);
        setPathControlsEnabled(true);
    } else {
        setActivePath(null);
        setPathControlsEnabled(false);
    }

    recalculatePathPlaybackTiming();
    // Reset playback state
    state.pathPlayback.currentElapsed = 0;
    state.pathPlayback.active = false;
    if (els.btns.playPause) els.btns.playPause.textContent = '▶';
    updatePathPlayback(performance.now());
}

function setPathControlsEnabled(enabled) {
    const opacity = enabled ? 1.0 : 0.5;
    const pointerEvents = enabled ? 'auto' : 'none';
    
    if (els.pathControls) {
        els.pathControls.style.opacity = opacity;
        els.pathControls.style.pointerEvents = pointerEvents;
    }
}

function resetCamera() {
    state.camera = {
        globalLevel: 0,
        x: 0.5,
        y: 0.5
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
                updateInputAvailability();
            }
        });
    });

    // Path Controls
    // els.pathSelect listener removed
    
    // Play/Pause Toggle
    els.btns.playPause.addEventListener('click', () => {
        if (!state.activePath) return;
        
        if (state.pathPlayback.active) {
            // Pause
            state.pathPlayback.active = false;
            els.btns.playPause.textContent = '▶';
            // elapsed is already tracked in updatePathPlayback, but let's ensure it's stable
            // No specific action needed as currentElapsed is updated in render loop or maintained
        } else {
            // Play
            // If we are at the end, restart
            if (state.pathPlayback.currentElapsed >= state.pathPlayback.totalDuration) {
                state.pathPlayback.currentElapsed = 0;
            }
            
            state.pathPlayback.active = true;
            state.pathPlayback.startTime = performance.now() - state.pathPlayback.currentElapsed;
            els.btns.playPause.textContent = '⏸';
        }
    });

    // Skip Buttons
    els.btns.start.addEventListener('click', () => {
        state.pathPlayback.currentElapsed = 0;
        if (state.pathPlayback.active) state.pathPlayback.startTime = performance.now();
        updatePathPlayback(state.pathPlayback.active ? performance.now() : 0); 
        // If paused, we need to force update with a fake 'now' that respects the 0 elapsed
        if (!state.pathPlayback.active) forceSeek(0);
    });

    els.btns.end.addEventListener('click', () => {
        state.pathPlayback.currentElapsed = state.pathPlayback.totalDuration;
        state.pathPlayback.active = false;
        els.btns.playPause.textContent = '▶';
        forceSeek(state.pathPlayback.totalDuration);
    });
    
    els.btns.back.addEventListener('click', () => {
        let t = state.pathPlayback.currentElapsed - 10000;
        if (t < 0) t = 0;
        state.pathPlayback.currentElapsed = t;
        if (state.pathPlayback.active) state.pathPlayback.startTime = performance.now() - t;
        else forceSeek(t);
    });

    els.btns.fwd.addEventListener('click', () => {
        let t = state.pathPlayback.currentElapsed + 10000;
        if (t > state.pathPlayback.totalDuration) t = state.pathPlayback.totalDuration;
        state.pathPlayback.currentElapsed = t;
        if (state.pathPlayback.active) state.pathPlayback.startTime = performance.now() - t;
        else forceSeek(t);
    });

    // Scrubber
    els.inputs.time.addEventListener('input', (e) => {
        state.pathPlayback.active = false; // Pause playback on scrub
        els.btns.playPause.textContent = '▶';
        
        const scrubbedFraction = parseFloat(e.target.value);
        const scrubbedTime = state.pathPlayback.totalDuration * scrubbedFraction;
        
        state.pathPlayback.currentElapsed = scrubbedTime;
        forceSeek(scrubbedTime);
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
    
    // Camera Inputs
    els.inputs.level.addEventListener('input', (e) => { 
        const lvl = parseInt(e.target.value);
        if (!Number.isNaN(lvl)) {
            state.camera.globalLevel = Math.max(0, lvl);
            updateUI(); 
        }
    });
    els.inputs.x.addEventListener('input', (e) => { state.camera.x = clamp01(parseFloat(e.target.value)); updateUI(); });
    els.inputs.y.addEventListener('input', (e) => { state.camera.y = clamp01(parseFloat(e.target.value)); updateUI(); });

    // Reset Button
    els.btnReset.addEventListener('click', resetCamera);

    window.addEventListener('resize', updateViewSize);
    
    // Initialize input state
    updateInputAvailability();
    
    // Ensure view size is updated initially
    updateViewSize();
}

function updateInputAvailability() {
    const disabled = state.mode === 'path';
    els.inputs.level.disabled = disabled;
    els.inputs.x.disabled = disabled;
    els.inputs.y.disabled = disabled;
    
    // Visually indicate disabled state for ranges/inputs if standard CSS doesn't cover it enough
    // (Browser default for disabled inputs is usually sufficient: greyed out and non-interactive)
}

// Helper to seek when paused
function forceSeek(elapsedTime) {
    updatePathPlaybackWithElapsed(elapsedTime);
}

function updateViewSize() {
    const rect = els.viewer.getBoundingClientRect();
    state.viewSize = { width: rect.width, height: rect.height };
}

// Camera Logic
function clamp01(v) {
    if (Number.isNaN(v) || !Number.isFinite(v)) return 0.5;
    return Math.min(1, Math.max(0, v));
}

function pan(dx, dy) {
    // Compute delta in normalized global units. One tile at current level spans 1 / 2^level.
    const scale = Math.pow(2, state.camera.globalLevel);
    const worldPerPixel = 1 / (LOGICAL_TILE_SIZE * scale);
    state.camera.x = clamp01(state.camera.x - dx * worldPerPixel);
    state.camera.y = clamp01(state.camera.y - dy * worldPerPixel);
    updateUI();
}

function zoom(amount) {
    state.camera.globalLevel = Math.max(0, state.camera.globalLevel + amount);
    updateUI();
}

function updateUI() {
    if (!els.vals.level) return;
    const lvl = Math.floor(state.camera.globalLevel);
    const zoomOffset = state.camera.globalLevel - lvl;
    els.vals.level.textContent = lvl + " (+ " + zoomOffset.toFixed(2) + ")";
    if (els.vals.x) els.vals.x.textContent = state.camera.x.toFixed(6);
    if (els.vals.y) els.vals.y.textContent = state.camera.y.toFixed(6);
    
    // Only update inputs if they are not focused to allow editing without overwrite
    if (document.activeElement !== els.inputs.level) els.inputs.level.value = lvl;
    if (document.activeElement !== els.inputs.x) els.inputs.x.value = state.camera.x;
    if (document.activeElement !== els.inputs.y) els.inputs.y.value = state.camera.y;
}

// Path Playback
const PATH_SPEED = {
    visualUnitsPerSecond: 2.0, // Increased by 4x from 0.5
    minSegmentMs: 300
};

let lastSpeedLogTime = 0; // For debug logging
let prevCameraStateForLog = null; // For instantaneous speed calculation

function cameraToGlobal(camera) {
    return {
        x: camera.x,
        y: camera.y,
        level: camera.globalLevel
    };
}

function segmentDurationMs(k1, k2) {
    // Calculate Visual Distance between two camera states
    const l1 = k1.globalLevel;
    const l2 = k2.globalLevel;
    const l_avg = (l1 + l2) / 2;
    
    // Scale factor at average level to convert Global Delta to Visual Delta
    // 1 Global Unit = 2^L_avg Visual Units (Screen Widths)
    const scale = Math.pow(2, l_avg);

    const g1 = cameraToGlobal(k1);
    const g2 = cameraToGlobal(k2);
    
    const dx = (g1.x - g2.x) * scale;
    const dy = (g1.y - g2.y) * scale;
    const dl = Math.abs(l1 - l2);
    
    // Visual Distance = Hypotenuse of Pan (in screens) and Zoom (in levels)
    const dist = Math.sqrt(dx*dx + dy*dy + dl*dl);
    
    const durationSeconds = dist / PATH_SPEED.visualUnitsPerSecond;
    return Math.max(durationSeconds * 1000, PATH_SPEED.minSegmentMs);
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

    // If active, calculate elapsed from start time
    if (state.pathPlayback.active) {
        state.pathPlayback.currentElapsed = now - state.pathPlayback.startTime;
        
        // Check for end
        if (state.pathPlayback.currentElapsed >= state.pathPlayback.totalDuration) {
            state.pathPlayback.currentElapsed = state.pathPlayback.totalDuration;
            state.pathPlayback.active = false;
            els.btns.playPause.textContent = '▶';
        }
    }

    updatePathPlaybackWithElapsed(state.pathPlayback.currentElapsed);

    // Speed Logging
    if (state.pathPlayback.active && now - lastSpeedLogTime > 1000) { // Log approximately every second when active
        if (prevCameraStateForLog) {
            const currentProgress = state.pathPlayback.currentElapsed / state.pathPlayback.totalDuration;
            // Get previous progress for accurate dt
            const prevElapsed = Math.max(0, state.pathPlayback.currentElapsed - (now - lastSpeedLogTime));
            const prevProgress = prevElapsed / state.pathPlayback.totalDuration;

            const camCurrent = state.pathSampler.cameraAtProgress(currentProgress);
            const camPrev = state.pathSampler.cameraAtProgress(prevProgress);

            if (camCurrent && camPrev) {
                const l1 = camPrev.globalLevel;
                const l2 = camCurrent.globalLevel;
                const l_avg = (l1 + l2) / 2;
                const scale = Math.pow(2, l_avg);

                const dx = (camCurrent.x - camPrev.x) * scale;
                const dy = (camCurrent.y - camPrev.y) * scale;
                const dl = l2 - l1;

                const dt_ms = now - lastSpeedLogTime;
                // Convert to units per second (visual units or levels)
                const inst_visual_speed = Math.sqrt(dx*dx + dy*dy + dl*dl) / (dt_ms / 1000);
                const inst_level_speed = dl / (dt_ms / 1000);
                
                console.log(`[Playback Speed] Lvl=${camCurrent.globalLevel.toFixed(2)} | Visual=${inst_visual_speed.toFixed(2)} unit/s | Level=${inst_level_speed.toFixed(2)} lvl/s`);
            }
        }
        lastSpeedLogTime = now;
        // Capture a snapshot of the current camera state, including global values
        prevCameraStateForLog = { 
            globalLevel: state.camera.globalLevel, 
            x: state.camera.x,
            y: state.camera.y
        };
    }
}

function updatePathPlaybackWithElapsed(elapsed) {
    if (!state.activePath || !state.pathSampler || state.pathPlayback.totalDuration <= 0) return;

    const clamped = Math.min(Math.max(elapsed, 0), state.pathPlayback.totalDuration);
    const progress = state.pathPlayback.totalDuration > 0 ? (clamped / state.pathPlayback.totalDuration) : 0;
    const cam = state.pathSampler.cameraAtProgress(progress);
    if (!cam) return;

    state.camera.globalLevel = cam.globalLevel;
    state.camera.x = cam.x;
    state.camera.y = cam.y;

    updateUI();

    // Update scrubber position
    if (els.inputs.time && state.pathPlayback.totalDuration > 0) {
        const currentFraction = clamped / state.pathPlayback.totalDuration;
        els.inputs.time.value = currentFraction.toFixed(4);
    }
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

    const camX_T = state.camera.x * Math.pow(2, level);
    const camY_T = state.camera.y * Math.pow(2, level);
    
    const displayScale = Math.pow(2, state.camera.globalLevel - level);
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
    if (state.mode === 'path') {
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
    const baseLevel = Math.floor(state.camera.globalLevel);
    const childOpacity = state.camera.globalLevel - baseLevel;

    for (let level = 0; level <= baseLevel; level++) {
        updateLayer(level, 1.0, targetTiles);
    }
    
    // Child layer (fade in) above the current level.
    updateLayer(baseLevel + 1, childOpacity, targetTiles);
    
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
