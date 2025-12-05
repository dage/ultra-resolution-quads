const ViewUtils = require('../shared/view_utils');
const Decimal = require('../shared/libs/decimal.min.js');

// Ensure Decimal precision
Decimal.set({ precision: 1000 });

console.log("Running Precision Tests...");

// Test Case A: Deep Zoom Coordinates
// 2^200 is approx 1.6e60
// We offset by 1e-50, which is significant enough at this scale?
// 1e-50 * 2^200 = 1e10. So yes, it's a huge offset in tiles.
const camera = {
    x: new Decimal("0.5").plus(new Decimal("1e-50")),
    y: new Decimal("0.5"),
    globalLevel: 200
};

// Viewport settings
const viewWidth = 1920;
const viewHeight = 1080;
const tileSize = 512;

console.log(`Camera Level: ${camera.globalLevel}`);
console.log(`Camera X: ${camera.x.toFixed(60)}...`);

const visible = ViewUtils.getVisibleTilesForLevel(camera, 200, viewWidth, viewHeight, tileSize);

console.log(`Visible Tiles Count: ${visible.tiles.length}`);
if (visible.tiles.length === 0) {
    console.error("FAIL: No tiles visible!");
    process.exit(1);
}

const firstTile = visible.tiles[0];
console.log(`First Tile: Level ${firstTile.level}, X=${firstTile.x}, Y=${firstTile.y}`);

// Verify X is a large integer string
if (typeof firstTile.x !== 'string') {
    console.error("FAIL: Tile X should be a string (BigInt representation).");
    process.exit(1);
}

// Check if it looks like a big integer
if (!/^\d+$/.test(firstTile.x)) {
    console.error(`FAIL: Tile X is not a valid integer string: ${firstTile.x}`);
    process.exit(1);
}

// Verify correctness roughly
// x index should be near floor(camera.x * 2^200)
// The camera is at 0.5 + 1e-50
// The center tile should be floor((0.5 + 1e-50) * 2^200)
// The returned tiles include the viewport range.
// We check if the camera position is INSIDE or very close to the returned tiles range.
const camX_Tiles = camera.x.times(Decimal.pow(2, 200));
const minX = new Decimal(visible.minX);
const maxX = new Decimal(visible.maxX);

console.log(`Camera X in Tiles: ${camX_Tiles.toFixed(2)}`);
console.log(`Visible X Range: ${minX} - ${maxX}`);

if (camX_Tiles.lessThan(minX) || camX_Tiles.greaterThan(maxX.plus(1))) {
    console.error("FAIL: Camera is outside the visible tile range!");
    process.exit(1);
}

console.log("PASS: Deep Zoom Coordinates");

// Test Case B: Smooth Panning
console.log("\nTest Case B: Small Pan");
const camera2 = { ...camera, x: camera.x.plus(new Decimal("1e-60")) };
const visible2 = ViewUtils.getVisibleTilesForLevel(camera2, 200, viewWidth, viewHeight, tileSize);
// It should return similar tiles, possibly shifted if we crossed a boundary.
console.log(`Shifted Camera X in Tiles: ${camera2.x.times(Decimal.pow(2, 200)).toFixed(2)}`);
console.log("PASS: Calculations performed without error.");
