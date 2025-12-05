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
        const t0 = Date.now();
        
        // 1. Calculate Half-Diagonal (Radius) of the Viewport in Pixels
        const viewRadiusPx = Math.sqrt((viewWidth/2)**2 + (viewHeight/2)**2);

        // 2. Calculate Global Units per Pixel
        const worldSizePx = Decimal.pow(2, camera.globalLevel).times(tileSize);
        const globalUnitsPerPixel = new Decimal(1).div(worldSizePx);

        // 3. Calculate Radius in Global Units
        const radiusGlobal = globalUnitsPerPixel.times(viewRadiusPx);

        // 4. Determine Bounds in Global Coordinates
        const minGx = camera.x.minus(radiusGlobal);
        const maxGx = camera.x.plus(radiusGlobal);
        const minGy = camera.y.minus(radiusGlobal);
        const maxGy = camera.y.plus(radiusGlobal);

        // 5. Convert to Tile Coordinates at Target Level
        const levelScale = Decimal.pow(2, targetLevel);
        
        const minTx = minGx.times(levelScale);
        const maxTx = maxGx.times(levelScale);
        const minTy = minGy.times(levelScale);
        const maxTy = maxGy.times(levelScale);

        // 6. Determine Integer Tile Bounds
        const limit = Decimal.pow(2, targetLevel);
        
        const startX_dec = minTx.floor();
        const endX_dec   = maxTx.floor();
        const startY_dec = minTy.floor();
        const endY_dec   = maxTy.floor();
        
        const zero = new Decimal(0);
        const maxIdx = limit.minus(1);

        const startX = startX_dec.lessThan(zero) ? zero : startX_dec;
        const endX   = endX_dec.greaterThan(maxIdx) ? maxIdx : endX_dec;
        const startY = startY_dec.lessThan(zero) ? zero : startY_dec;
        const endY   = endY_dec.greaterThan(maxIdx) ? maxIdx : endY_dec;

        // Check bounds size
        const diffX = endX.minus(startX).toNumber();
        const diffY = endY.minus(startY).toNumber();
        if (diffX > 100 || diffY > 100) console.error(`WARNING: Massive loop detected at Level ${targetLevel}: ${diffX}x${diffY}`);

        // Optimization: Radius in tile units for circular crop
        const radiusInTiles = radiusGlobal.times(levelScale);
        const centerTx = camera.x.times(levelScale);
        const centerTy = camera.y.times(levelScale);
        
        // Calculate radius squared in standard number (it's small, ~2-3 tiles)
        // Add buffer (0.75)
        const radiusSq_num = (radiusInTiles.toNumber() + 0.75) ** 2;

        const startX_bi = BigInt(startX.toFixed(0));
        const endX_bi   = BigInt(endX.toFixed(0));
        const startY_bi = BigInt(startY.toFixed(0));
        const endY_bi   = BigInt(endY.toFixed(0));
        
        // Optimize Loop:
        // We need (x + 0.5 - centerTx)^2 + (y + 0.5 - centerTy)^2 < r^2
        // x is BigInt. centerTx is Decimal.
        // Let centerTx_bi = BigInt(centerTx.floor())
        // Let centerTx_frac = centerTx.minus(centerTx_bi).toNumber()
        // dist = (x - centerTx_bi) + 0.5 - centerTx_frac
        
        const centerTx_dec_floor = centerTx.floor();
        const centerTy_dec_floor = centerTy.floor();
        
        const centerTx_bi = BigInt(centerTx_dec_floor.toFixed(0));
        const centerTy_bi = BigInt(centerTy_dec_floor.toFixed(0));
        
        const centerTx_frac = centerTx.minus(centerTx_dec_floor).toNumber();
        const centerTy_frac = centerTy.minus(centerTy_dec_floor).toNumber();

        const tiles = [];
        
        for (let x = startX_bi; x <= endX_bi; x++) {
            // Convert BigInt difference to Number (safe because viewport is small)
            const diffX = Number(x - centerTx_bi);
            const distX = diffX + 0.5 - centerTx_frac;
            const distX2 = distX * distX;

            for (let y = startY_bi; y <= endY_bi; y++) {
                const diffY = Number(y - centerTy_bi);
                const distY = diffY + 0.5 - centerTy_frac;
                
                if (distX2 + distY * distY < radiusSq_num) {
                    tiles.push({ level: targetLevel, x: x.toString(), y: y.toString() });
                }
            }
        }
        
        return {
            minX: startX_bi.toString(), maxX: endX_bi.toString(),
            minY: startY_bi.toString(), maxY: endY_bi.toString(),
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
