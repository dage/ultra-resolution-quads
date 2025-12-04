
window.telemetryEvents = []; // This will store all raw events
window.loggedTileStates = new Map(); // key: "datasetId|level|x|y", value: { loaded: bool, firstVisible: time }

const logEvent = (type, tileKey, cameraState, now, extra = {}) => {
    const parts = tileKey.split('|');
    window.telemetryEvents.push({
        type: type,
        time: now,
        tileId: `${parts[1]}/${parts[2]}/${parts[3]}`, // "level/x/y" format
        level: parseInt(parts[1]),
        x: parseInt(parts[2]),
        y: parseInt(parts[3]),
        camera: { ...cameraState },
        ...extra
    });
};

// Override the getTileImage function to track requests
const originalGetTileImage = window.getTileImage;
window.getTileImage = function(datasetId, level, x, y) {
    const tileKey = `${datasetId}|${level}|${x}|${y}`;
    logEvent('requested', tileKey, window.appState.camera, performance.now());

    const canvas = originalGetTileImage(datasetId, level, x, y);
    // Add a property to the canvas to track its loading status
    canvas.addEventListener('load', () => {
        logEvent('loaded', tileKey, window.appState.camera, performance.now());
    });
    // This assumes originalGetTileImage uses an img or loads into canvas
    // If it's the worker, we need to intercept worker's message.
    // Given the current main.js structure, the worker `onmessage` handles `bitmap`
    // Let's modify the worker's onmessage handler to log 'loaded'
    return canvas;
};


// Intercept worker messages for 'loaded' event
// This is a bit tricky since the worker communication is internal to main.js
// We need to make sure this script runs AFTER main.js initializes the worker
// The `window.telemetryData` getter will aggregate the events from loggedTileStates.
// This is not correct. The worker callback is inside main.js and not exposed.
// Let's rely on `el.isLoaded` property.

window.externalLoopHook = function(state, now) {
    if (!state.activeDatasetId || !window.activeTileElements) return;

    // Debug: Log progress every 60 frames (approx 1 sec)
    if (!window._lastLog || now - window._lastLog > 1000) {
        console.log(`Hook: Level ${state.camera.globalLevel.toFixed(2)}, ActiveTiles: ${window.activeTileElements.size}`);
        window._lastLog = now;
    }

    // Iterate over all active tiles
    for (const [tileKey, el] of window.activeTileElements) {
        const parts = tileKey.split('|');
        const tileId = `${parts[1]}/${parts[2]}/${parts[3]}`; // "level/x/y" format

        let tileState = window.loggedTileStates.get(tileKey);
        if (!tileState) {
            tileState = {
                requested: false,
                loaded: false,
                firstVisible: null,
                events: []
            };
            window.loggedTileStates.set(tileKey, tileState);
            logEvent('requested', tileKey, state.camera, now);
        }

        // Check if loaded (el.isLoaded is set by main.js after worker callback)
        if (el.isLoaded && !tileState.loaded) {
            tileState.loaded = true;
            logEvent('loaded', tileKey, state.camera, now);
        }

        // Check visibility (opacity > 0.01 and within viewport)
        const styleOpacity = parseFloat(el.style.opacity || 0);
        const rect = el.getBoundingClientRect();
        const inViewport = (
            rect.top < window.innerHeight && 
            rect.bottom > 0 &&
            rect.left < window.innerWidth && 
            rect.right > 0
        );

        if (styleOpacity > 0.01 && inViewport && !tileState.firstVisible) {
            tileState.firstVisible = now;
            logEvent('visible', tileKey, state.camera, now, { opacity: styleOpacity });
        }
    }
};

// Make sure `run_browser_experiment.py` extracts `window.telemetryEvents`
// by assigning it to `window.telemetryData` when requested.
Object.defineProperty(window, 'telemetryData', {
    get: function() {
        return window.telemetryEvents;
    }
});
