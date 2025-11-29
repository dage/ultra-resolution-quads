/**
 * shared/view_utils.js
 * 
 * Pure mathematical utilities for calculating visible tiles based on camera state.
 * adaptable for use in both Frontend (JS) and Backend (via generic porting or CLI).
 */

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.ViewUtils = factory();
    }
}(typeof self !== 'undefined' ? self : this, function() {

    /**
     * Calculates the range of tiles visible for a specific level using a Bounding Circle.
     * This is rotation-invariant and simpler than calculating rotated corners.
     * 
     * @param {Object} camera - { x, y, globalLevel } (x,y are 0-1 normalized)
     * @param {number} targetLevel - The integer level we want to find tiles for.
     * @param {number} viewWidth - Viewport width in pixels.
     * @param {number} viewHeight - Viewport height in pixels.
     * @param {number} tileSize - logical tile size (e.g. 512).
     * @returns {Object} { minX, maxX, minY, maxY, tiles: [] }
     */
    function getVisibleTilesForLevel(camera, targetLevel, viewWidth, viewHeight, tileSize) {
        // 1. Calculate Half-Diagonal (Radius) of the Viewport in Pixels
        // This is the distance from center to the farthest corner.
        const viewRadiusPx = Math.sqrt((viewWidth/2)**2 + (viewHeight/2)**2);

        // 2. Calculate Global Units per Pixel
        // World Size = 2^cameraLevel * tileSize
        const worldSizePx = Math.pow(2, camera.globalLevel) * tileSize;
        const globalUnitsPerPixel = 1.0 / worldSizePx;

        // 3. Calculate Radius in Global Units
        const radiusGlobal = viewRadiusPx * globalUnitsPerPixel;

        // 4. Determine Bounds in Global Coordinates
        const minGx = camera.x - radiusGlobal;
        const maxGx = camera.x + radiusGlobal;
        const minGy = camera.y - radiusGlobal;
        const maxGy = camera.y + radiusGlobal;

        // 5. Convert to Tile Coordinates at Target Level
        const levelScale = Math.pow(2, targetLevel);
        
        const minTx = minGx * levelScale;
        const maxTx = maxGx * levelScale;
        const minTy = minGy * levelScale;
        const maxTy = maxGy * levelScale;

        // 6. Determine Integer Tile Bounds
        const limit = Math.pow(2, targetLevel);
        
        // We use floor/ceil to fully cover the range
        const startX = Math.max(0, Math.floor(minTx));
        const endX   = Math.min(limit - 1, Math.floor(maxTx));
        const startY = Math.max(0, Math.floor(minTy));
        const endY   = Math.min(limit - 1, Math.floor(maxTy));
        
        // Optimization: Radius in tile units for circular crop
        // We already computed minTx/maxTx based on 'radiusGlobal * levelScale'
        // Radius in tiles = radiusGlobal * levelScale
        const radiusInTiles = radiusGlobal * levelScale;
        const centerTx = camera.x * levelScale;
        const centerTy = camera.y * levelScale;
        const radiusSq = radiusInTiles * radiusInTiles;

        const tiles = [];
        for (let x = startX; x <= endX; x++) {
            for (let y = startY; y <= endY; y++) {
                // Check if any part of the tile is within the radius?
                // Conservative check: distance from center of tile to center of camera?
                // Or strictly: is the tile within the circle?
                // The 'radius' covers the farthest corner of the viewport.
                // So any tile intersecting this circle *might* be visible.
                // A safe check is: dist(tileCenter, camCenter) < radius + tileDiagonal/2
                // Tile Diagonal/2 = sqrt(0.5^2 + 0.5^2) = ~0.707.
                
                const distX = (x + 0.5) - centerTx;
                const distY = (y + 0.5) - centerTy;
                const dSq = distX*distX + distY*distY;
                
                // We add a small buffer (0.75) to account for tile corner intersection
                if (dSq < (radiusInTiles + 0.75) ** 2) {
                    tiles.push({ level: targetLevel, x, y });
                }
            }
        }

        return {
            minX: startX, maxX: endX,
            minY: startY, maxY: endY,
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
        // Only if we are zooming "into" it (fraction > 0) or just to be ready
        // Use a threshold to avoid loading next level if we are exactly on the integer?
        // Usually good to always load to allow smooth start of zoom.
        // However, strict culling might check if (camera.globalLevel > baseLevel)
        const child = getVisibleTilesForLevel(camera, baseLevel + 1, viewWidth, viewHeight, tileSize);
        required.push(...child.tiles);
        
        return required;
    }

    return {
        getVisibleTilesForLevel: getVisibleTilesForLevel,
        getRequiredTiles: getRequiredTiles
    };

}));
