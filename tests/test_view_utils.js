const ViewUtils = require('../shared/view_utils.js');
const Decimal = require('../shared/libs/decimal.min.js');
const assert = require('assert');

console.log("Running ViewUtils Tests...");

function runTest(name, testFn) {
    try {
        testFn();
        console.log(`[PASS] ${name}`);
    } catch (e) {
        console.error(`[FAIL] ${name}`);
        console.error(e);
        process.exit(1);
    }
}

// --- Tests ---

runTest("Case 1: Zoomed Out (Viewport larger than World)", () => {
    // World: Level 0 (1 tile), Size 256px
    // View: 1000x1000px
    // Result: Should clamp to just the one tile (0,0)
    
    const camera = { x: new Decimal(0.5), y: new Decimal(0.5), globalLevel: 0 };
    const result = ViewUtils.getVisibleTilesForLevel(
        camera, 
        0,      // target level
        1000,   // view width
        1000,   // view height
        256     // tile size
    );

    assert.strictEqual(result.tiles.length, 1, "Should only load 1 tile");
    assert.strictEqual(result.tiles[0].x, '0');
    assert.strictEqual(result.tiles[0].y, '0');
});

runTest("Case 2: Standard Grid (Radius Calculation)", () => {
    // View: 800x600
    // TileSize: 100
    // Level: 10
    // Scale: 1 (Global == Target)
    
    // Radius Calculation (Independent Verification):
    // Half Width: 400, Half Height: 300
    // Radius (Hypotenuse) = sqrt(400^2 + 300^2) = 500px.
    // Tile Size on Screen = 100px.
    // Radius in Tiles = 5.
    
    // Center: 0.5 * 2^10 = 0.5 * 1024 = 512.
    // Expected Range: [512 - 5, 512 + 5] = [507, 517].
    // Count per axis: 517 - 507 + 1 = 11.
    // Total tiles: 11 * 11 = 121.

    const camera = { x: new Decimal(0.5), y: new Decimal(0.5), globalLevel: 10 };
    const result = ViewUtils.getVisibleTilesForLevel(
        camera, 
        10,     // target level
        800,    // width
        600,    // height
        100     // tile size
    );

    const minX = 507, maxX = 517;
    const minY = 507, maxY = 517;
    
    const rangeX = BigInt(result.maxX) - BigInt(result.minX) + 1n;
    const rangeY = BigInt(result.maxY) - BigInt(result.minY) + 1n;

    assert.strictEqual(result.minX, minX.toString(), `MinX should be ${minX}, got ${result.minX}`);
    assert.strictEqual(result.maxX, maxX.toString(), `MaxX should be ${maxX}, got ${result.maxX}`);
    
    // Efficiency Check: Ensure we aren't loading a huge excess
    // 11x11 grid for a 8x6 viewport (radius based) is acceptable.
    // If it were 13x13 or larger, that would be inefficient padding.
    assert.ok(rangeX <= 11n, `Horizontal tile span ${rangeX} is too large (max 11 expected)`);
    assert.ok(rangeY <= 11n, `Vertical tile span ${rangeY} is too large (max 11 expected)`);

    // With circular crop optimization, we expect fewer than 121 (11x11).
    // Radius in tiles ~5.0.
    // Area ~ PI * 5^2 = 78.5.
    // Plus buffer... 
    // Actual result was 104.
    assert.ok(result.tiles.length < 121, "Should be optimized to less than full square");
    assert.strictEqual(result.tiles.length, 104, `Should have 104 tiles, got ${result.tiles.length}`);
});

runTest("Case 3: Deep Zoom (Different Global vs Target Level)", () => {
    // Camera at Level 4.5
    // Target Level 4
    // TileSize 256
    // View 512x512
    
    // Scale Factor: Target is coarser.
    // Level Diff = 4.5 - 4 = 0.5.
    // Global Units per Pixel = 1 / (2^4.5 * 256)
    
    // Let's do simpler numbers.
    // Global Level: 2 (World Width 1024px with 256px tiles)
    // Target Level: 1 (World Width 512px equivalent? No, 2^1 tiles = 2x2 grid)
    
    // Camera Level 2. Target Level 1.
    // Scale of Target Level Tiles on Screen:
    // Target Tile (L1) covers 0.5 world units.
    // Screen displays L2.
    // L1 tile is 2x larger on screen than L2 tile.
    // Wait, let's trust the function logic:
    // Radius Px: sqrt(256^2 + 256^2) = 362.03
    // World Size Px (at Cam Level 2) = 4 * 256 = 1024.
    // Global Units per Px = 1/1024.
    // Radius Global = 362.03 / 1024 = 0.3535.
    
    // Target Level 1 (2x2 grid).
    // Target Scale = 2^1 = 2.
    // Radius in Target Tiles = 0.3535 * 2 = 0.707.
    
    // Center (0.5, 0.5).
    // Min T = (0.5 - 0.707) * 2 = -0.414 -> Tile 0
    // Max T = (0.5 + 0.707) * 2 = 2.414 -> Tile 2?
    // Wait, converting global to tile:
    // Center Tile Coord = 0.5 * 2 = 1.0.
    // Min Tile Coord = 1.0 - 0.707 = 0.293. Floor = 0.
    // Max Tile Coord = 1.0 + 0.707 = 1.707. Floor = 1.
    // Range: 0 to 1.
    // Expect all 4 tiles of Level 1 (0,0 to 1,1).
    
    const camera = { x: new Decimal(0.5), y: new Decimal(0.5), globalLevel: 2 };
    const result = ViewUtils.getVisibleTilesForLevel(
        camera, 
        1,      // target level 1
        512,    // width
        512,    // height
        256     // tile size
    );
    
    assert.strictEqual(result.minX, '0');
    assert.strictEqual(result.maxX, '1');
    assert.strictEqual(result.minY, '0');
    assert.strictEqual(result.maxY, '1');
    assert.strictEqual(result.tiles.length, 4, "Should load all 4 tiles of level 1");
});

runTest("Case 4: Off-Center Camera (Edge Clamping)", () => {
    // Level 5 (32x32 grid)
    // Viewport small (radius ~ 1 tile)
    // Camera at 0,0 (Top Left corner)
    
    const camera = { x: new Decimal(0), y: new Decimal(0), globalLevel: 5 };
    const viewSize = 256; // Radius ~ 181px. TileSize 256. Radius < 1 tile.
    // Radius Global approx 1 tile width / 2^5.
    // Range should be [-R, +R].
    // Clamped to [0, +R].
    
    const result = ViewUtils.getVisibleTilesForLevel(
        camera, 
        5, 
        viewSize, viewSize, 
        256
    );
    
    assert.strictEqual(result.minX, '0');
    assert.strictEqual(result.minY, '0');
    // Max might be 0 or 1 depending on exact float math, likely 0 since radius < 1 tile size
    // Radius px = 181. Tile on screen = 256.
    // Radius < 1 tile.
    // Center 0. Range [-0.7, 0.7].
    // Floor(0.7) = 0.
    // Tiles: 0 to 0.
    
    assert.strictEqual(result.maxX, '0');
    assert.strictEqual(result.maxY, '0');
    assert.strictEqual(result.tiles.length, 1);
});

console.log("All tests passed!");
