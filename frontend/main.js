const BASE_DATA_URI = '..';
const LIVE_SERVER_URI = 'http://localhost:8000';
// Logical tile size for layout; actual image resolution can differ.
const LOGICAL_TILE_SIZE = 512;

// --- Intelligent Request Manager ------------------------------------------------
class RequestManager {
    constructor() {
        this.queue = [];
        this.activeRequests = new Map();
        // Separate lanes for live (expensive) vs worker/static (cheap)
        this.limits = {
            live: 1,
            worker: 6
        };
        this.activeCounts = {
            live: 0,
            worker: 0
        };
        this.liveInFlight = null; // Enforce single live render at a time
        this.liveQueuedClass = new WeakMap();
        this.liveQueuedElements = new Set();
        this.latestCamera = null;
        this.latestView = null;
        this.workerIdToRequest = new Map();
        this.nextWorkerId = 0;
    }

    request(datasetId, level, x, y, options = {}) {
        const id = `${datasetId}|${level}|${x}|${y}`;
        const type = options.type || 'worker';

        // If a live request for this tile is already active/queued, rebind it to the new DOM
        // element so the rendering/queued indicators stay in sync when tiles are recreated.
        const active = this.activeRequests.get(id);
        if (active) {
            if (active.type === 'live' && type === 'live' && active.options) {
                if (options.element && active.options.element !== options.element) {
                    this.clearQueueClass(active.options.element);
                    active.options.element = options.element;
                }
                if (options.imgEl) active.options.imgEl = options.imgEl;
                if (this.liveInFlight === id && active.options.element) {
                    active.options.element.classList.add('rendering');
                }
            }
            return;
        }

        const queued = this.queue.find(r => r.id === id);
        if (queued) {
            if (queued.type === 'live' && type === 'live') {
                if (options.element && queued.options && queued.options.element !== options.element) {
                    this.clearQueueClass(queued.options.element);
                }
                queued.options = { ...(queued.options || {}), ...options, type: 'live' };
                this.updateQueuePositions();
            }
            return;
        }

        this.queue.push({ id, datasetId, level, x, y, status: 'QUEUED', type, options });
        this.process();
    }

    resolveWorkerRequest(workerId) {
        const reqId = this.workerIdToRequest.get(workerId);
        if (reqId) this.workerIdToRequest.delete(workerId);
        return reqId;
    }

    dispatch(req) {
        const opts = req.options || {};
        if (opts.type === 'live') {
            const imgEl = opts.imgEl || opts.element;
            const url = opts.src;
            if (!imgEl || !url) {
                this.complete(req.id, false);
                return;
            }
            this.liveInFlight = req.id;
            this.clearQueueClass(imgEl);
            if (opts.element) {
                opts.element.classList.add('rendering');
            }

            const retryDelay = opts.retryDelayMs ?? 200;
            const scheduleRetry = () => {
                // Remove any existing queued copy before retrying to avoid duplicates
                this.queue = this.queue.filter(r => r.id !== req.id);
                const retryReq = { ...req, status: 'QUEUED' };
                setTimeout(() => {
                    this.queue.unshift(retryReq);
                    this.process();
                }, retryDelay);
            };

            const startFetch = async () => {
                try {
                    const resp = await fetch(url, { cache: 'no-store' });
                    if (resp.status === 503) {
                        this.complete(req.id, false);
                        scheduleRetry();
                        return;
                    }
                    if (!resp.ok) {
                        replaceLiveTileWithCanvas(req.id, opts.element, null, imgEl);
                        this.complete(req.id, false);
                        return;
                    }

                    const blob = await resp.blob();
                    const objectUrl = URL.createObjectURL(blob);

            const swapFromBitmap = (bitmap) => {
                replaceLiveTileWithCanvas(req.id, opts.element, bitmap, imgEl);
            };
                    try {
                        const bitmap = await createImageBitmap(blob);
                        swapFromBitmap(bitmap);
                        bitmap.close();
                        URL.revokeObjectURL(objectUrl);
                        this.complete(req.id, true);
                        return;
                    } catch (err) {
                        console.warn('createImageBitmap failed, falling back to img path', err);
                    }

                    imgEl.onload = () => {
                        URL.revokeObjectURL(objectUrl);
                        swapFromBitmap(null);
                        this.complete(req.id, true);
                    };

                    imgEl.onerror = () => {
                        URL.revokeObjectURL(objectUrl);
                        this.complete(req.id, false);
                        scheduleRetry();
                    };

                    imgEl.src = objectUrl;
                } catch (err) {
                    console.warn('Live tile fetch error, retrying:', err);
                    this.complete(req.id, false);
                    scheduleRetry();
                }
            };

            startFetch();
        } else {
            // Worker-based tile load
            const workerId = this.nextWorkerId++;
            this.workerIdToRequest.set(workerId, req.id);
            imageLoader.postMessage({ id: workerId, url: opts.url });
        }
    }

    process() {
        // Sort by visual impact if we have camera/view
        if (this.latestCamera && this.latestView) {
            const cam = this.latestCamera;
            const view = this.latestView;
            this.queue.sort((a, b) => {
                const pa = this.getVisualPriority(a, cam, view);
                const pb = this.getVisualPriority(b, cam, view);
                // Larger visible area first, then closer to center
                if (pb.area !== pa.area) return pb.area - pa.area;
                return pa.dist - pb.dist;
            });
        }

        for (let i = 0; i < this.queue.length; i++) {
            const req = this.queue[i];
            const lane = req.type || 'worker';
            if (lane === 'live' && this.liveInFlight && this.liveInFlight !== req.id) {
                continue; // Single live guard
            }
            if (this.activeCounts[lane] < (this.limits[lane] ?? 0)) {
                this.queue.splice(i, 1);
                i--;
                req.status = 'DISPATCHED';
                this.activeRequests.set(req.id, req);
                this.activeCounts[lane] = (this.activeCounts[lane] || 0) + 1;
                this.dispatch(req);
            }
        }

        // Update visual queue positions for remaining queued items
        this.updateQueuePositions();
    }

    complete(id, success = true) {
        const req = this.activeRequests.get(id);
        if (req && success && req.options && req.options.type === 'live') {
            // Cache newly rendered tiles so subsequent visits treat them as existing.
            const manifestKey = `${req.level}/${req.x}/${req.y}`;
            state.availableTiles.add(manifestKey);
        }

        if (req) {
            this.activeRequests.delete(id);
            const lane = req.type || 'worker';
            if (this.activeCounts[lane] > 0) {
                this.activeCounts[lane]--;
            }
            if (lane === 'live' && this.liveInFlight === id) {
                this.liveInFlight = null;
            }
            if (lane === 'live' && req.options && req.options.element) {
                this.clearQueueClass(req.options.element);
                req.options.element.classList.remove('rendering');
            }
        }
        syncQueueStatusUI(); // Immediate feedback after each tile
        this.process();
    }

    prune(camera, viewSize) {
        this.latestCamera = camera;
        this.latestView = viewSize;

        if (!camera || !viewSize) return;

        // 1. Identify which levels are currently in the queue
        const levelsToCheck = new Set();
        for (const req of this.queue) {
            levelsToCheck.add(req.level);
        }

        // 2. Build a "Allow List" of valid tiles for those levels
        // We use the exact same ViewUtils logic as the renderer.
        const validTileKeys = new Set();
        
        // Optimization: Only check levels close to the camera to avoid
        // expensive calculations for stale requests deep in the queue.
        const baseLevel = Math.floor(camera.globalLevel);
        
        for (const lvl of levelsToCheck) {
            if (Math.abs(lvl - baseLevel) > 2) continue;

            const visible = ViewUtils.getVisibleTilesForLevel(
                camera, 
                lvl, 
                viewSize.width, 
                viewSize.height, 
                LOGICAL_TILE_SIZE
            );
            
            for (const t of visible.tiles) {
                validTileKeys.add(`${lvl}|${t.x}|${t.y}`);
            }
        }

        // 3. Filter the queue using the Allow List
        // This implicitly handles the "Radius" check because invalid 
        // tiles simply won't be in validTileKeys.
        let prunedCount = 0;
        const filtered = [];

        for (const req of this.queue) {
            const key = `${req.level}|${req.x}|${req.y}`;
            if (validTileKeys.has(key)) {
                filtered.push(req);
            } else {
                prunedCount++;
                if (req.type === 'live' && req.options && req.options.element) {
                    this.clearQueueClass(req.options.element);
                }
            }
        }
        
        if (prunedCount > 0) {
            // Optional: console.log(`Pruned ${prunedCount} off-screen tiles`);
        }
        
        this.queue = filtered;
    }

    getVisualDistance(req, camera, viewSize) {
        const bounds = this.getTileBounds(req, camera, viewSize);
        const centerX = (bounds.minX + bounds.maxX) / 2;
        const centerY = (bounds.minY + bounds.maxY) / 2;
        const viewCenterX = viewSize ? viewSize.width / 2 : 0;
        const viewCenterY = viewSize ? viewSize.height / 2 : 0;
        const dx = centerX - viewCenterX;
        const dy = centerY - viewCenterY;
        return dx * dx + dy * dy;
    }

    getVisualPriority(req, camera, viewSize) {
        const bounds = this.getTileBounds(req, camera, viewSize);
        const centerX = (bounds.minX + bounds.maxX) / 2;
        const centerY = (bounds.minY + bounds.maxY) / 2;
        const viewCenterX = viewSize ? viewSize.width / 2 : 0;
        const viewCenterY = viewSize ? viewSize.height / 2 : 0;
        const dx = centerX - viewCenterX;
        const dy = centerY - viewCenterY;
        const dist = dx * dx + dy * dy;

        // Approximate visible area within viewport
        const w = viewSize ? viewSize.width : 0;
        const h = viewSize ? viewSize.height : 0;
        const ix = Math.max(0, Math.min(bounds.maxX, w) - Math.max(bounds.minX, 0));
        const iy = Math.max(0, Math.min(bounds.maxY, h) - Math.max(bounds.minY, 0));
        const area = Math.round(ix * iy); // larger area => higher priority

        return { area, dist };
    }

    getTileBounds(req, camera, viewSize) {
        const camLevel = camera ? Number(camera.globalLevel || 0) : 0;
        const camX = toNumber(camera ? camera.x : 0.5);
        const camY = toNumber(camera ? camera.y : 0.5);
        const levelScale = Math.pow(2, req.level);
        const camX_T = camX * levelScale;
        const camY_T = camY * levelScale;
        const tileCenterX_T = Number(req.x) + 0.5;
        const tileCenterY_T = Number(req.y) + 0.5;

        const tileSizeOnScreen = LOGICAL_TILE_SIZE * Math.pow(2, camLevel - req.level);
        const halfSize = tileSizeOnScreen / 2;

        const dxTiles = tileCenterX_T - camX_T;
        const dyTiles = tileCenterY_T - camY_T;

        const centerXScreen = (viewSize ? viewSize.width : 0) / 2 + dxTiles * tileSizeOnScreen;
        const centerYScreen = (viewSize ? viewSize.height : 0) / 2 + dyTiles * tileSizeOnScreen;

        return {
            minX: centerXScreen - halfSize,
            maxX: centerXScreen + halfSize,
            minY: centerYScreen - halfSize,
            maxY: centerYScreen + halfSize
        };
    }

    updateQueuePositions() {
        const newlyQueued = new Set();
        let position = 1;
        for (const req of this.queue) {
            if (req.type === 'live' && req.options && req.options.element) {
                this.applyQueueClass(req.options.element, position);
                newlyQueued.add(req.options.element);
            }
            position++;
        }
        // Clear badges for elements no longer queued
        for (const el of this.liveQueuedElements) {
            if (!newlyQueued.has(el)) {
                this.clearQueueClass(el);
            }
        }
        this.liveQueuedElements = newlyQueued;
    }

    applyQueueClass(el, position) {
        const prev = this.liveQueuedClass.get(el);
        if (prev) el.classList.remove(prev);
        el.classList.add('queued');
        const label = position > 10 ? '10+' : String(position);
        const cls = position > 10 ? 'queued-10plus' : `queued-${label}`;
        el.classList.add(cls);
        this.liveQueuedClass.set(el, cls);
        el.dataset.queuePos = `#${label}`;
        if (el._queueBadge) {
            el._queueBadge.textContent = `#${label}`;
            el._queueBadge.classList.add('visible');
        }
    }

    clearQueueClass(el) {
        const prev = this.liveQueuedClass.get(el);
        if (prev) {
            el.classList.remove(prev);
            this.liveQueuedClass.delete(el);
        }
        el.classList.remove('queued');
        delete el.dataset.queuePos;
        if (el._queueBadge) {
            el._queueBadge.textContent = '';
            el._queueBadge.classList.remove('visible');
        }
    }
}

function toNumber(val) {
    if (typeof val === 'number') return val;
    if (val && typeof val.toNumber === 'function') return val.toNumber();
    return parseFloat(val || 0);
}

function flashTileLoaded(el) {
    if (!el) return;
    el.classList.add('flash-loaded');
    setTimeout(() => el.classList.remove('flash-loaded'), 400);
}

// Application State
// Decimal precision is set dynamically in loadDataset based on max_level.

const state = {
    datasets: [],
    activeDatasetId: null,
    config: null,
    // Telemetry Data
    telemetry: [],
    autoplayPending: false,
    liveRender: false,
    camera: {
        globalLevel: 1,
        x: new Decimal("0.5"),
        y: new Decimal("0.5"),
        rotation: 0
    },
    capturedKeyframes: [],
    isDragging: false,
    lastMouse: { x: 0, y: 0 },
    viewSize: { width: 0, height: 0 },
    
    // Experience (Path Playback) State
    path: null,
    activePath: null,
    activeKeyframeIdx: -1, // Tracks the currently selected or active keyframe
    pathSampler: null,
    experience: {
        active: false,
        startTime: 0,
        currentElapsed: 0,
        segmentDurations: [],
        totalDuration: 0
    },
    // Tile Manifest
    availableTiles: new Set(),
    // Backend status for live render health indicator
    backendStatus: null
};

let queueStatusInterval = null;
// Expose state for debugging and automation
window.appState = state;
let ui;
let els;

// Instantiate request manager (smart network valve)
const requestManager = new RequestManager();

// Initialization
async function init() {
    ui = new UIManager(state, {
        onDatasetChange: (value) => loadDataset(value),
        onLiveRenderToggle: (enabled) => handleLiveRenderToggle(enabled),
        onUpdateExperience: (now) => updateExperience(now),
        onForceSeek: (t) => forceSeek(t),
        onPan: (dx, dy) => pan(dx, dy),
        onZoom: (amount) => zoom(amount),
        onClampDecimal: (value) => clamp01(new Decimal(value)),
        
        // Path Panel Callbacks
        onPathJump: (idx) => jumpToKeyframe(idx),
        onPathAdd: () => addKeyframeAtCurrentView(),
        onPathDelete: (idx) => deleteKeyframe(idx),
        onPathCopy: (btn) => copyPathToClipboard(btn)
    });
    els = ui.els;

    const resp = await fetch(`${BASE_DATA_URI}/datasets/index.json`);
    const data = await resp.json();
    state.datasets = data.datasets;
    
    populateDatasetSelect();
    
    // Initialize UI (PathPanel, Listeners) early so it catches dataset/path updates
    ui.init();

    // Parse Query Parameters
    const params = new URLSearchParams(window.location.search);
    const datasetParam = params.get('dataset');
    const autoplayParam = params.get('autoplay');

    let targetDatasetId = state.datasets.length > 0 ? state.datasets[0].id : null;

    if (datasetParam) {
        const exists = state.datasets.find(d => d.id === datasetParam);
        if (exists) {
            targetDatasetId = datasetParam;
        }
    }

    if (targetDatasetId) {
        await loadDataset(targetDatasetId);
        if (els.datasetSelect) els.datasetSelect.value = targetDatasetId;
    }

    if (autoplayParam === 'true') {
        state.autoplayPending = true;
    }
    
    setupUIControls();
    ui.updateCursor();
    
    // Initialize transform origin for rotation
    if (els.layers) els.layers.style.transformOrigin = 'center center';
    
    requestAnimationFrame(renderLoop);
}

// --- Path Manipulation Logic ---

function jumpToKeyframe(index) {
    if (!state.activePath || !state.activePath.keyframes) return;
    const kf = state.activePath.keyframes[index];
    if (!kf) return;
    
    // Update active index
    state.activeKeyframeIdx = index;
    if (ui) ui.updatePathActive(index);

    // 1. Set Camera to exact keyframe (for precision)
    const cam = kf.camera || kf;
    state.camera.globalLevel = cam.globalLevel ?? cam.level ?? 0;
    state.camera.x = new Decimal(cam.x ?? 0.5);
    state.camera.y = new Decimal(cam.y ?? 0.5);
    state.camera.rotation = cam.rotation || 0;

    // 2. Sync Timeline / Progress Bar
    if (state.pathSampler && state.pathSampler.stops && state.pathSampler.stops.length > index) {
        // Stops correspond to keyframes. stops[0] = 0.
        const dist = state.pathSampler.stops[index];
        // Calculate time based on constant speed
        const timeSec = dist / PATH_SPEED.visualUnitsPerSecond;
        const timeMs = timeSec * 1000;
        
        // UPDATE STATE
        state.experience.currentElapsed = timeMs;
        
        // IMPORTANT: Reset StartTime so next Play click doesn't jump!
        // This effectively "seeks" the internal clock to match the new visual position.
        state.experience.startTime = performance.now() - timeMs;

        // UPDATE UI
        if (els.inputs.time && state.experience.totalDuration > 0) {
             // Use clamp to ensure 0-1 range
             const progress = Math.min(Math.max(timeMs / state.experience.totalDuration, 0), 1);
             els.inputs.time.value = progress.toFixed(4);
        }
    }
    
    if (ui) ui.update();
}

function addKeyframeAtCurrentView() {
    // 1. Create Keyframe from current camera
    const kf = {
        camera: {
            globalLevel: state.camera.globalLevel,
            x: state.camera.x.toString(), // Store as string for JSON precision
            y: state.camera.y.toString(),
            rotation: state.camera.rotation || 0
        }
    };

    // 2. Ensure we have an active path object
    if (!state.activePath) {
        state.activePath = { keyframes: [] };
    }
    if (!state.activePath.keyframes) {
        state.activePath.keyframes = [];
    }

    // 3. Insert AFTER the currently active keyframe
    // If nothing selected (idx = -1), insert at end (or 0 if empty)
    let insertAt = state.activePath.keyframes.length;
    if (state.activeKeyframeIdx !== -1 && state.activeKeyframeIdx < state.activePath.keyframes.length) {
        insertAt = state.activeKeyframeIdx + 1;
    }

    state.activePath.keyframes.splice(insertAt, 0, kf);
    
    // Update active index to the new frame
    state.activeKeyframeIdx = insertAt;

    // 4. Rebuild
    updatePathState();
}

function deleteKeyframe(index) {
    if (!state.activePath || !state.activePath.keyframes) return;
    state.activePath.keyframes.splice(index, 1);
    
    // Adjust active index
    if (state.activeKeyframeIdx === index) {
        // If we deleted the active one, select the previous one (or 0)
        state.activeKeyframeIdx = Math.max(0, index - 1);
        if (state.activePath.keyframes.length === 0) state.activeKeyframeIdx = -1;
    } else if (state.activeKeyframeIdx > index) {
        // Shift down
        state.activeKeyframeIdx--;
    }

    updatePathState();
}

function updatePathState() {
    // Rebuild Sampler
    state.pathSampler = CameraPath.buildSampler(state.activePath);
    
    // Update Timing
    recalculateExperienceTiming();
    
    // Enable/Disable Controls based on validity
    const isValid = state.activePath && state.activePath.keyframes && state.activePath.keyframes.length >= 2;
    setExperienceControlsEnabled(isValid);

    if (!isValid) {
        // Stop playback if path is broken
        state.experience.active = false;
        if (els.btns.playPause) els.btns.playPause.textContent = '▶';
        state.experience.currentElapsed = 0;
        state.experience.totalDuration = 0;
    }

    // Update UI
    if (ui) {
        ui.updatePathList(state.activePath ? state.activePath.keyframes : []);
        ui.updatePathActive(state.activeKeyframeIdx);
        ui.updateInputAvailability(); // Refresh disabled states
    }
}

function copyPathToClipboard(btn) {
    if (!state.activePath || !state.activePath.keyframes) return;
    
    // Format nicely
    const json = JSON.stringify(state.activePath.keyframes, null, 2);
    
    if (navigator.clipboard) {
        navigator.clipboard.writeText(json).then(() => {
            const originalText = btn.textContent;
            btn.textContent = "✓";
            setTimeout(() => btn.textContent = originalText, 1000);
            console.log("Path copied to clipboard.");
        }).catch(err => {
            console.error("Clipboard failed:", err);
            console.log("Path JSON:", json);
        });
    } else {
        console.log("Path JSON:", json);
    }
}


function setupUIControls() {
    // 1. Fullscreen Logic
    if (els.btnFullscreen) {
        const iconEnter = '<path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>';
        const iconExit = '<path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>';

        const updateFsIcon = () => {
            const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement;
            const svg = els.btnFullscreen.querySelector('svg');
            if (svg) svg.innerHTML = isFullscreen ? iconExit : iconEnter;
            els.btnFullscreen.title = isFullscreen ? "Exit Fullscreen" : "Toggle Fullscreen";
            

        };

        els.btnFullscreen.addEventListener('click', () => {
            const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement;
            if (!isFullscreen) {
                const req = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen;
                if (req) req.call(document.documentElement).catch(console.error);
            } else {
                const exit = document.exitFullscreen || document.webkitExitFullscreen;
                if (exit) exit.call(document);
            }
        });

        document.addEventListener('fullscreenchange', updateFsIcon);
        document.addEventListener('webkitfullscreenchange', updateFsIcon);
        
        // Initial check
        updateFsIcon();
    }

    // 2. UI Toggle Logic
    if (els.btnToggleUI && els.app) {
        // Icons for "Show Panel" (Sidebar left) vs "Hide Panel" (Sidebar right)
        // Hide Panel (Right Arrow ->)
        const iconHide = '<path d="M4 18h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2zm0-10h16v8H4V8z"/>'; 
        // Show Panel (Left Arrow <-) -- Just using a simple placeholder icon logic for now
        // Actually, let's use specific icons:
        // Open: Panel visible. Icon should suggest "Close".
        const iconPanelVisible = '<path d="M5 19h14V5H5v14zm4-7h6v2H9v-2z"/>'; // A simple box or minus? Let's stick to the generic sidebar icons.
        
        // Better Material Design Icons
        // "Web Asset" (like a browser window with sidebar)
        const iconUI = '<path d="M19 4H5c-1.11 0-2 .9-2 2v12c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.89-2-2-2zm0 14H5V8h14v10z"/>';
        const iconUIOff = '<path d="M19 4H5c-1.11 0-2 .9-2 2v12c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.89-2-2-2zm0 14H5V8h14v10z"/>'; // Same for now, toggling opacity/slash?
        
        // Let's just toggle opacity or something. Or use a specific "Sidebar" icon.
        // Sidebar Open (to hide): 'Subject' or 'View Sidebar'
        // Sidebar Closed (to show):
        
        els.btnToggleUI.addEventListener('click', () => {
            els.app.classList.toggle('ui-collapsed');
            if (ui) ui.updateToggleIcon();
        });
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

function updateDatasetQueryParam(datasetId) {
    if (!datasetId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('dataset', datasetId);
    history.replaceState(null, '', url.toString());
}

async function loadDataset(id) {
    state.activeDatasetId = id;
    updateDatasetQueryParam(id);
    // Load Config
    const respConfig = await fetch(`${BASE_DATA_URI}/datasets/${id}/config.json`);
    state.config = await respConfig.json();

    // Adjust Precision for Deep Zoom if necessary
    // Default 50 is good for ~Level 100.
    // Formula: digits ~= level * 0.3 + 20
    let maxLevel = 20;
    if (state.config.render_config && typeof state.config.render_config.max_level === 'number') {
        maxLevel = state.config.render_config.max_level;
    }

    // Also check the path keyframes, as they dictate the actual depth during playback
    if (state.config.render_config && state.config.render_config.path && Array.isArray(state.config.render_config.path.keyframes)) {
        for (const kf of state.config.render_config.path.keyframes) {
            const cam = kf.camera || kf;
            let level = 0;
            if (typeof cam.globalLevel === 'number') {
                level = cam.globalLevel;
            } else if (typeof cam.level === 'number') {
                level = cam.level + (cam.zoomOffset || 0);
            }
            if (level > maxLevel) maxLevel = level;
        }
    }

    const neededPrecision = Math.max(50, Math.ceil(maxLevel * 0.35 + 20));
    console.log(`Dataset Max Level: ${maxLevel}. Setting Decimal precision to ${neededPrecision}.`);
    Decimal.set({ precision: neededPrecision });

    // Load Tile Manifest (to avoid 404s)
    state.availableTiles.clear();
    try {
        const respTiles = await fetch(`${BASE_DATA_URI}/datasets/${id}/tiles.json`);
        if (respTiles.ok) {
            const tilesList = await respTiles.json();
            // Use a Set for O(1) lookups
            state.availableTiles = new Set(tilesList);
            console.log(`Loaded manifest: ${state.availableTiles.size} tiles available.`);
        } else {
            console.warn("No tiles.json found; tile checking disabled (assumes all exist).");
        }
    } catch (e) {
        console.warn("Failed to load tiles.json:", e);
    }
    
    // Load Paths
    // New Standard: path is embedded in config.json under render_config
    if (state.config && state.config.render_config && state.config.render_config.path) {
        state.path = state.config.render_config.path;
    } else {
        state.path = null;
    }
    autoSelectPath();

    resetCamera();
}

function setActivePath(path) {
    const resolved = (typeof CameraPath !== 'undefined' && CameraPath.resolvePathMacros)
        ? CameraPath.resolvePathMacros(path)
        : (path || null);

    state.activePath = resolved;
    if (ui) ui.updatePathList(state.activePath ? state.activePath.keyframes : []);

    if (!resolved || typeof CameraPath === 'undefined') {
        state.pathSampler = null;
        return;
    }
    state.pathSampler = CameraPath.buildSampler(resolved);
}

function autoSelectPath() {
    // Automatically select the path if available
    if (state.path) {
        setActivePath(state.path);
        setExperienceControlsEnabled(true);
    } else {
        setActivePath(null);
        setExperienceControlsEnabled(false);
    }

    recalculateExperienceTiming();
    // Reset playback state
    state.experience.currentElapsed = 0;
    state.experience.active = false;
    if (els.btns.playPause) els.btns.playPause.textContent = '▶';
    forceSeek(0);
    if (ui) ui.updateInputAvailability();
}

function setExperienceControlsEnabled(enabled) {
    const opacity = enabled ? 1.0 : 0.5;
    const pointerEvents = enabled ? 'auto' : 'none';
    
    if (els.experienceControls) {
        els.experienceControls.style.opacity = opacity;
        els.experienceControls.style.pointerEvents = pointerEvents;
    }
}

function startQueueStatusPolling() {
    if (queueStatusInterval) return;
    queueStatusInterval = setInterval(() => {
        if (!state.liveRender) return;
        refreshBackendStatus();
        syncQueueStatusUI();
    }, 300);
}

function stopQueueStatusPolling() {
    if (queueStatusInterval) {
        clearInterval(queueStatusInterval);
        queueStatusInterval = null;
    }
}

function handleLiveRenderToggle(enabled) {
    state.liveRender = enabled;
    if (enabled) {
        if (els && els.queueStatus) els.queueStatus.classList.remove('hidden');
        refreshBackendStatus();
        syncQueueStatusUI();
        startQueueStatusPolling();
    } else {
        stopQueueStatusPolling();
        state.backendStatus = null;
        if (els && els.queueStatus) els.queueStatus.classList.add('hidden');
    }
}

function syncQueueStatusUI() {
    if (!ui) return;
    ui.updateQueueStatus({
        pending: requestManager.queue.length,
        activeLive: requestManager.activeCounts.live,
        backend: state.backendStatus
    });
}

let backendStatusFetchInFlight = false;
async function refreshBackendStatus() {
    if (!state.liveRender) return;
    if (backendStatusFetchInFlight) return;
    backendStatusFetchInFlight = true;
    try {
        const resp = await fetch(`${LIVE_SERVER_URI}/status`, { cache: 'no-store' });
        if (resp.ok) {
            const data = await resp.json();
            state.backendStatus = data;
        } else {
            state.backendStatus = null;
        }
    } catch (err) {
        state.backendStatus = null;
    } finally {
        backendStatusFetchInFlight = false;
    }
}

function resetCamera() {
    const firstKeyframeCam = state.activePath && state.activePath.keyframes && state.activePath.keyframes.length > 0
        ? state.activePath.keyframes[0].camera
        : null;

    const cam = firstKeyframeCam || {
        globalLevel: 1,
        x: 0.5,
        y: 0.5,
        rotation: 0
    };

    state.camera.globalLevel = cam.globalLevel ?? cam.level ?? 0;
    state.camera.x = new Decimal(cam.x ?? 0.5);
    state.camera.y = new Decimal(cam.y ?? 0.5);
    state.camera.rotation = cam.rotation || 0;

    state.experience.currentElapsed = 0;
    state.experience.active = false;
    if (ui) ui.update();
    if (ui) ui.updateInputAvailability();
    forceSeek(0);
}

// Helper to seek when paused
function forceSeek(elapsedTime) {
    updateExperienceWithElapsed(elapsedTime);
}

// Camera Logic
function clamp01(v) {
    if (v && typeof v.lessThan === 'function') {
        if (v.lessThan(0)) return new Decimal(0);
        if (v.greaterThan(1)) return new Decimal(1);
        return v;
    }
    if (Number.isNaN(v) || !Number.isFinite(v)) return 0.5;
    return Math.min(1, Math.max(0, v));
}

function pan(dx, dy) {
    // Compute delta in normalized global units. One tile at current level spans 1 / 2^level.
    const scale = Decimal.pow(2, state.camera.globalLevel);
    const worldPerPixel = new Decimal(1).div(scale.times(LOGICAL_TILE_SIZE));
    
    // Rotate vector according to camera rotation
    // Screen to World rotation is +rot (because World to Screen is -rot).
    // We drag the world, so the camera moves in the opposite direction of the drag.
    // dCamera_Screen = (-dx, -dy)
    // dCamera_World = Rot(r) * dCamera_Screen
    // dx_w (subtracted from cam.x) should be: dx * cos - dy * sin
    // dy_w (subtracted from cam.y) should be: dx * sin + dy * cos
    
    const r = state.camera.rotation || 0;
    const dx_w = dx * Math.cos(r) - dy * Math.sin(r);
    const dy_w = dx * Math.sin(r) + dy * Math.cos(r);

    state.camera.x = clamp01(state.camera.x.minus(worldPerPixel.times(dx_w)));
    state.camera.y = clamp01(state.camera.y.minus(worldPerPixel.times(dy_w)));
    if (ui) ui.update();
}

function zoom(amount) {
    state.camera.globalLevel = Math.max(0, state.camera.globalLevel + amount);
    if (ui) ui.update();
}

// Experience (Path Playback) Logic
const PATH_SPEED = {
    visualUnitsPerSecond: 2.0, // Increased by 4x from 0.5
    minSegmentMs: 300
};

function cameraToGlobal(camera) {
    return {
        x: camera.x,
        y: camera.y,
        level: camera.globalLevel,
        rotation: camera.rotation || 0
    };
}

function recalculateExperienceTiming() {
    if (!state.activePath || !state.activePath.keyframes || state.activePath.keyframes.length < 2) {
        state.experience.segmentDurations = [];
        state.experience.totalDuration = 0;
        return;
    }

    // Use the Sampler's pre-calculated cumulative distances (stops) to determine segment lengths.
    // This ensures the playback timing matches the interpolation logic (Single Source of Truth).
    if (!state.pathSampler || !state.pathSampler.stops) {
        // If sampler isn't ready, we can't calculate timing. 
        // This might happen if CameraPath lib is missing or path is invalid.
        state.experience.segmentDurations = [];
        state.experience.totalDuration = 0;
        return;
    }

    const stops = state.pathSampler.stops;
    const durations = [];
    
    // Keyframe i to i+1 corresponds to stops[i] to stops[i+1]
    for (let i = 0; i < state.activePath.keyframes.length - 1; i++) {
        // Distance for this segment
        const dist = stops[i+1] - stops[i];
        
        const durationSeconds = dist / PATH_SPEED.visualUnitsPerSecond;
        durations.push(Math.max(durationSeconds * 1000, PATH_SPEED.minSegmentMs));
    }
    
    state.experience.segmentDurations = durations;
    state.experience.totalDuration = durations.reduce((a, b) => a + b, 0);
}

function updateExperience(now) {
    if (!state.activePath || !state.activePath.keyframes || state.activePath.keyframes.length < 2) return;
    if (!state.experience.segmentDurations.length || state.experience.totalDuration <= 0) return;

    // If active, calculate elapsed from start time
    if (state.experience.active) {
        state.experience.currentElapsed = now - state.experience.startTime;
        
        // Check for end
        if (state.experience.currentElapsed >= state.experience.totalDuration) {
            state.experience.currentElapsed = state.experience.totalDuration;
            state.experience.active = false;
            els.btns.playPause.textContent = '▶';
            if (ui) ui.updateInputAvailability();
        }

        updateExperienceWithElapsed(state.experience.currentElapsed);
    }
}

function updateExperienceWithElapsed(elapsed) {
    if (!state.activePath || !state.pathSampler || state.experience.totalDuration <= 0) return;

    const clamped = Math.min(Math.max(elapsed, 0), state.experience.totalDuration);

    // Update Active Highlight in Path Panel
    if (ui && state.experience.segmentDurations) {
        let t = 0;
        let activeIdx = 0;
        // Find which segment we are in
        for (let i = 0; i < state.experience.segmentDurations.length; i++) {
            if (clamped < t + state.experience.segmentDurations[i]) {
                activeIdx = i;
                break;
            }
            t += state.experience.segmentDurations[i];
            activeIdx = i + 1; // If we passed this segment, we are at least at the next one
        }
        // Clamp to last keyframe
        if (activeIdx >= state.activePath.keyframes.length) {
            activeIdx = state.activePath.keyframes.length - 1;
        }
        
        // Sync state and UI
        state.activeKeyframeIdx = activeIdx;
        ui.updatePathActive(activeIdx);
    }

    const progress = state.experience.totalDuration > 0 ? (clamped / state.experience.totalDuration) : 0;
    const cam = state.pathSampler.cameraAtProgress(progress);
    if (!cam) return;

    state.camera.globalLevel = cam.globalLevel;
    state.camera.x = cam.x;
    state.camera.y = cam.y;
    state.camera.rotation = cam.rotation || 0;

    if (ui) ui.update();

    // Update scrubber position
    if (els.inputs.time && state.experience.totalDuration > 0) {
        const currentFraction = clamped / state.experience.totalDuration;
        els.inputs.time.value = currentFraction.toFixed(4);
    }
}

// Rendering
const activeTileElements = new Map(); // Key: "level|x|y", Value: DOM Element
window.activeTileElements = activeTileElements; // Expose for telemetry

// Replace a live tile wrapper with a canvas (used after live render finishes or fails).
function replaceLiveTileWithCanvas(id, container, bitmap, imgEl) {
    if (!container) return;

    const w = (bitmap && bitmap.width) || (imgEl && imgEl.naturalWidth) || LOGICAL_TILE_SIZE;
    const h = (bitmap && bitmap.height) || (imgEl && imgEl.naturalHeight) || LOGICAL_TILE_SIZE;

    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.className = 'tile';
    canvas.style.width = `${LOGICAL_TILE_SIZE}px`;
    canvas.style.height = `${LOGICAL_TILE_SIZE}px`;
    canvas.style.transformOrigin = 'top left';

    const cache = container._tileCache || {};
    const ctx = canvas.getContext('2d');
        if (bitmap) {
            ctx.drawImage(bitmap, 0, 0, w, h);
        } else if (imgEl && imgEl.complete) {
            ctx.drawImage(imgEl, 0, 0, w, h);
        } else {
        ctx.clearRect(0, 0, w, h);
    }

    canvas.isLoaded = true;
    canvas.classList.add('loaded');
    flashTileLoaded(canvas);
    canvas._tileCache = { ...cache };
    if (cache.transform) canvas.style.transform = cache.transform;
    if (cache.opacity) canvas.style.opacity = cache.opacity;
    if (cache.zIndex !== undefined) canvas.style.zIndex = cache.zIndex;

    const parent = container.parentNode;
    if (parent) parent.replaceChild(canvas, container);
    if (activeTileElements.get(id) === container) {
        activeTileElements.set(id, canvas);
    }
}

// Worker for image loading
const imageLoader = new Worker('image_loader.worker.js');

imageLoader.onmessage = function(e) {
    const { id, bitmap, error } = e.data;
    const key = requestManager.resolveWorkerRequest(id);

    if (!key) {
        if (bitmap) bitmap.close();
        return;
    }

    // Check if tile is still active in the DOM/Virtual Map
    const el = activeTileElements.get(key);
    if (!el) {
        if (bitmap) bitmap.close();
        requestManager.complete(key, !!bitmap);
        return;
    }

    if (bitmap) {
        // Update canvas internal resolution to match the source image (High DPI support)
        el.width = bitmap.width;
        el.height = bitmap.height;

        const ctx = el.getContext('2d');
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close();
        el.isLoaded = true;
        el.classList.add('loaded');
    } else {
        // console.warn('Worker error for tile:', key, error);
        // Handle error (maybe transparent or error placeholder)
        el.isLoaded = true; // Mark as processed to avoid hanging 'areTilesReady'
    }

    requestManager.complete(key, !!bitmap);
};

function getTileImage(datasetId, level, x, y) {
    const manifestKey = `${level}/${x}/${y}`;
    const exists = state.availableTiles.has(manifestKey);
    const useLive = state.liveRender && !exists;

    const key = `${datasetId}|${level}|${x}|${y}`;

    if (useLive) {
        const container = document.createElement('div');
        container.className = 'tile live-tile';
        container.style.width = `${LOGICAL_TILE_SIZE}px`;
        container.style.height = `${LOGICAL_TILE_SIZE}px`;
        container.style.transformOrigin = 'top left';
        container._tileCache = { transform: '', opacity: '', zIndex: '' };
        container.isLoaded = false;

        const img = document.createElement('img');
        img.className = 'live-img';
        img.width = LOGICAL_TILE_SIZE;
        img.height = LOGICAL_TILE_SIZE;
        img.draggable = false;
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.display = 'block';
        img.style.pointerEvents = 'none';

        const badge = document.createElement('span');
        badge.className = 'queue-badge';
        badge.textContent = '';
        container._queueBadge = badge;

        img.onload = () => {
            container.isLoaded = true;
            container.classList.add('loaded');
            requestManager.complete(key, true);
        };
        img.onerror = () => {
            container.isLoaded = true;
            requestManager.complete(key, false);
        };

        container.appendChild(img);
        container.appendChild(badge);

        requestManager.request(datasetId, level, x, y, {
            type: 'live',
            element: container,
            imgEl: img,
            src: `${LIVE_SERVER_URI}/live/${datasetId}/${level}/${x}/${y}.webp`
        });

        return container;
    }

    const canvas = document.createElement('canvas');
    canvas.width = LOGICAL_TILE_SIZE;
    canvas.height = LOGICAL_TILE_SIZE;
    canvas.className = 'tile';
    canvas.style.width = `${LOGICAL_TILE_SIZE}px`;
    canvas.style.height = `${LOGICAL_TILE_SIZE}px`;
    canvas.style.transformOrigin = 'top left';
    canvas._tileCache = { transform: '', opacity: '', zIndex: '' };
    canvas.isLoaded = false;

    requestManager.request(datasetId, level, x, y, {
        type: 'worker',
        url: `${BASE_DATA_URI}/datasets/${datasetId}/${level}/${x}/${y}.webp`
    });

    return canvas;
}

// Simple helper to batch DOM inserts so we touch the tree once per frame.
function createTileBatch(container) {
    const fragment = document.createDocumentFragment();
    return {
        add(el) { fragment.appendChild(el); },
        flush() {
            if (fragment.childNodes.length) {
                container.appendChild(fragment);
            }
        }
    };
}

function updateLayer(level, opacity, targetTiles) {
    if (opacity <= 0.001) return;

    if (typeof ViewUtils === 'undefined') return;

    // Use shared logic to find exactly which tiles are visible
    const visible = ViewUtils.getVisibleTilesForLevel(
        state.camera, 
        level, 
        state.viewSize.width, 
        state.viewSize.height, 
        LOGICAL_TILE_SIZE
    );

    const tileSize = LOGICAL_TILE_SIZE;
    const displayScale = Math.pow(2, state.camera.globalLevel - level);
    const tileSizeOnScreen = tileSize * displayScale;
    const centerX = state.viewSize.width / 2;
    const centerY = state.viewSize.height / 2;

    // Center of the world in global coords is state.camera.x, state.camera.y
    // We need to compute screen position for each tile.
    
    // We calculate camera position in "Tile Units" at this level using Decimal
    const levelScale = Decimal.pow(2, level);
    const camX_T = state.camera.x.times(levelScale);
    const camY_T = state.camera.y.times(levelScale);

    visible.tiles.forEach(t => {
        const x = t.x; // String
        const y = t.y; // String

        // Check manifest when not live rendering; in live mode we want to allow
        // requests for tiles that aren't pre-generated so the backend can render
        // them on demand.
        if (!state.liveRender && state.availableTiles.size > 0) {
            const manifestKey = `${level}/${x}/${y}`;
            if (!state.availableTiles.has(manifestKey)) {
                return; // Skip non-existent tile when relying on static tiles
            }
        }

        const key = `${state.activeDatasetId}|${level}|${x}|${y}`;
        
        // Screen position using precomputed relX/relY from getVisibleTilesForLevel.
        const screenX = centerX + (t.relX * tileSizeOnScreen);
        const screenY = centerY + (t.relY * tileSizeOnScreen);
        
        targetTiles.set(key, {
            datasetId: state.activeDatasetId,
            level, x, y,
            tx: screenX,
            ty: screenY,
            scale: displayScale,
            opacity: opacity,
            zIndex: level
        });
    });
}

function areTilesReady() {
    // We want at least some tiles to be present to consider it 'ready'
    if (activeTileElements.size === 0) return false;
    for (const el of activeTileElements.values()) {
        if (!el.isLoaded) return false;
    }
    return true;
}

function updateQueueBadgeOrientation(rotationRad) {
    const angle = rotationRad || 0;
    for (const el of activeTileElements.values()) {
        if (el && el._queueBadge) {
            el._queueBadge.style.transform = `translate(-50%, -50%) rotate(${angle}rad)`;
        }
    }
}

function renderLoop() {
    // 1. Update View Size (Robust handling of resize & UI transitions)
    if (els.viewer) {
        const rect = els.viewer.getBoundingClientRect();
        state.viewSize.width = rect.width;
        state.viewSize.height = rect.height;
    }

    // Keep the request queue in sync with the current view (drop stale requests)
    requestManager.prune(state.camera, state.viewSize);
    // Refresh queued badges/positions in case the set changed after pruning
    requestManager.updateQueuePositions();

    const now = performance.now();

    // External Hook for Telemetry/Scripting
    if (typeof window.externalLoopHook === 'function') {
        window.externalLoopHook(state, now);
    }

    // Autoplay Logic
    if (state.autoplayPending) {
        if (areTilesReady()) {
            state.autoplayPending = false;
            console.log("Autoplay: Tiles ready. Starting playback.");
            
            if (state.activePath) {
                // Trigger Play
                state.experience.currentElapsed = 0;
                // Reset start time so it starts exactly now
                state.experience.startTime = now;
                state.experience.active = true;
                
                if (els.btns.playPause) els.btns.playPause.textContent = '⏸';
                if (ui) ui.updateInputAvailability();
            } else {
                console.warn("Autoplay: No active path found.");
            }
        }
    }

    updateExperience(now);
    
    // Apply global rotation
    if (els.layers) {
        const rot = state.camera.rotation || 0;
        els.layers.style.transform = `rotate(${-rot}rad)`;
        updateQueueBadgeOrientation(rot);
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

    // OPTIMIZED: Only render visible stack (Parent -> Base -> Child)
    // 1. Parent (Fallback for loading gaps)
    if (baseLevel > 0) {
        updateLayer(baseLevel - 1, 1.0, targetTiles);
    }

    // 2. Base Level (Current primary)
    updateLayer(baseLevel, 1.0, targetTiles);
    
    // 3. Child layer (fade in) above the current level.
    updateLayer(baseLevel + 1, childOpacity, targetTiles);
    
    // Reconciliation
    const batch = createTileBatch(els.layers);

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
            batch.add(el);
            activeTileElements.set(key, el);
        }
        
        // Update styles: position via translate, scale via transform.
        // We avoid rounding here to prevent per-tile rounding differences
        // from introducing tiny seams between tiles.
        const cached = el._tileCache || {};
        const overlapScale = props.scale * 1.001;   // quick and easy workaround of sub pixels seams between tiles
        const nextTransform = `translate(${props.tx}px, ${props.ty}px) scale(${overlapScale})`;
        const nextOpacity = props.opacity.toFixed(3);
        const nextZ = props.zIndex;

        if (cached.transform !== nextTransform) el.style.transform = nextTransform;
        if (cached.opacity !== nextOpacity) el.style.opacity = nextOpacity;
        if (cached.zIndex !== nextZ) el.style.zIndex = nextZ;

        el._tileCache = {
            transform: nextTransform,
            opacity: nextOpacity,
            zIndex: nextZ
        };
    }

    // Apply any new tiles in a single DOM append to minimize layout/paint churn.
    batch.flush();
    
    if (document.body.classList.contains('debug') && els.debugStats) {
        els.debugStats.textContent = `Tiles: ${activeTileElements.size}`;
    }
    
    requestAnimationFrame(renderLoop);
}

init();
