/**
 * shared/view_utils.js
 * 
 * Pure mathematical utilities for calculating visible tiles based on camera state.
 * adaptable for use in both Frontend (JS) and Backend (via generic porting or CLI).
 */

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        // Node.js: Require vendored file relative to this file
        const Decimal = require('./libs/decimal.min.js');
        module.exports = factory(Decimal);
    } else {
        // Browser: Expect global dependency
        root.ViewUtils = factory(root.Decimal);
    }
}(typeof self !== 'undefined' ? self : this, function(Decimal) {

    /**
     * Calculates the range of tiles visible for a specific level using a Bounding Circle.
     * This is rotation-invariant and simpler than calculating rotated corners.
     * 
     * @param {Object} camera - { x: Decimal, y: Decimal, globalLevel: Number }
     * @param {number} targetLevel - The integer level we want to find tiles for.
     * @param {number} viewWidth - Viewport width in pixels.
     * @param {number} viewHeight - Viewport height in pixels.
     * @param {number} tileSize - logical tile size (e.g. 512).
     * @returns {Object} { minX, maxX, minY, maxY, tiles: [] } -> x/y are BigInt or String
     */
    function getVisibleTilesForLevel(camera, targetLevel, viewWidth, viewHeight, tileSize) {
        // 1. Screen Space Setup (Float Math)
        // We calculate the search radius in "Tile Units" for the target level.
        const viewRadiusPx = Math.sqrt((viewWidth/2)**2 + (viewHeight/2)**2);
        
        // Scale of the target level relative to the current view
        // displayScale = (Size of Target Level Tile in Pixels) / (Size of Logical Tile)
        // If targetLevel == globalLevel, scale = 1.
        // If targetLevel < globalLevel (zoomed in), scale < 1 (target tiles are huge? No wait).
        // globalLevel = 10. targetLevel = 9.
        // World Size L10 = 1024 * tileSize.
        // World Size L9 = 512 * tileSize.
        // Screen shows L10 size.
        // L9 tile covers 2x L10 tiles.
        // So L9 tile is 2x bigger on screen.
        // displayScale = 2^(global - target).
        const zoomDiff = camera.globalLevel - targetLevel;
        const displayScale = Math.pow(2, zoomDiff);
        const tileSizeOnScreen = tileSize * displayScale;
        
        // How many tiles extend from the center to cover the viewport radius?
        const radiusInTiles = viewRadiusPx / tileSizeOnScreen;
        
        // Add a safe buffer for rotation and rounding
        // Old logic used floor(center - radius) which is roughly center - ceil(radius)
        const searchRadius = Math.ceil(radiusInTiles);
        
        if (searchRadius > 50) console.error(`WARNING: Massive loop detected at Level ${targetLevel}: Radius ${searchRadius}`);

        const radiusSq = (radiusInTiles + 0.75) ** 2; // Matching original buffer logic logic

        // 2. Global Anchor (High Precision)
        // We only do BigInt/Decimal math ONCE to find the center tile and offset.
        const levelScale = Decimal.pow(2, targetLevel);
        
        // Center position in Tile Coordinates
        const centerTx = camera.x.times(levelScale);
        const centerTy = camera.y.times(levelScale);
        
        const centerTx_dec_floor = centerTx.floor();
        const centerTy_dec_floor = centerTy.floor();
        
        // The integer tile index of the camera
        const centerTx_bi = BigInt(centerTx_dec_floor.toFixed(0));
        const centerTy_bi = BigInt(centerTy_dec_floor.toFixed(0));
        
        // The fractional offset within that tile [0, 1)
        const offsetX = centerTx.minus(centerTx_dec_floor).toNumber();
        const offsetY = centerTy.minus(centerTy_dec_floor).toNumber();

        // 3. Relative Loop (Fast Integer Math)
        const tiles = [];
        const limit = (1n << BigInt(targetLevel)) - 1n; // Max valid index
        
        // Track bounds for legacy return format
        let minX_bi = null, maxX_bi = null, minY_bi = null, maxY_bi = null;

        for (let dx = -searchRadius; dx <= searchRadius; dx++) {
            // Distance from camera to tile center (X axis)
            // Tile Center X = (centerTx_bi + dx) + 0.5
            // Camera X      = centerTx_bi + offsetX
            // Dist          = dx + 0.5 - offsetX
            const distX = dx + 0.5 - offsetX;
            const distX2 = distX * distX;

            // Optimization: Pre-check X range before inner loop
            if (distX2 > radiusSq && Math.abs(distX) > radiusInTiles + 1) continue; 
            // (The secondary check handles the fact that the circle might be wide, 
            // but simple dist2 check handles most)

            for (let dy = -searchRadius; dy <= searchRadius; dy++) {
                const distY = dy + 0.5 - offsetY;
                
                if (distX2 + distY * distY < radiusSq) {
                    // 4. Lazy Reconstruction (BigInt) & Bounds Check
                    const x = centerTx_bi + BigInt(dx);
                    const y = centerTy_bi + BigInt(dy);
                    
                    // Wrap or Clamp? The project seems to clamp (based on previous code)
                    // Previous code: clamped startX/endX to 0..limit
                    if (x < 0n || x > limit || y < 0n || y > limit) {
                        continue;
                    }

                    // Update Bounds (for legacy support)
                    if (minX_bi === null || x < minX_bi) minX_bi = x;
                    if (maxX_bi === null || x > maxX_bi) maxX_bi = x;
                    if (minY_bi === null || y < minY_bi) minY_bi = y;
                    if (maxY_bi === null || y > maxY_bi) maxY_bi = y;

                    tiles.push({ 
                        level: targetLevel, 
                        x: x.toString(), 
                        y: y.toString(),
                        // New Contract: Pre-calculated relative position
                        // relX = Tile Left Edge - Camera Position
                        relX: dx - offsetX,
                        relY: dy - offsetY
                    });
                }
            }
        }
        
        return {
            minX: minX_bi !== null ? minX_bi.toString() : centerTx_bi.toString(),
            maxX: maxX_bi !== null ? maxX_bi.toString() : centerTx_bi.toString(),
            minY: minY_bi !== null ? minY_bi.toString() : centerTy_bi.toString(),
            maxY: maxY_bi !== null ? maxY_bi.toString() : centerTy_bi.toString(),
            tiles
        };
    }

    /**
     * determining the "Stack" of tiles needed.
     * Usually: Current Level, Parent Level (fallback), and Next Level (if fading).
     */
    function getRequiredTiles(camera, viewWidth, viewHeight, tileSize) {
        const baseLevel = Math.floor(camera.globalLevel);
        const required = [];

        // 1. Base Level (Current Crisp)
        const base = getVisibleTilesForLevel(camera, baseLevel, viewWidth, viewHeight, tileSize);
        required.push(...base.tiles);

        // 2. Parent Level (Fallback/Background)
        // We always want one level up to cover loading gaps or transparency
        if (baseLevel > 0) {
            const parent = getVisibleTilesForLevel(camera, baseLevel - 1, viewWidth, viewHeight, tileSize);
            required.push(...parent.tiles);
        }

        // 3. Child Level (Next Detail)
        const child = getVisibleTilesForLevel(camera, baseLevel + 1, viewWidth, viewHeight, tileSize);
        required.push(...child.tiles);
        
        return required;
    }

    return {
        getVisibleTilesForLevel: getVisibleTilesForLevel,
        getRequiredTiles: getRequiredTiles
    };

}));
