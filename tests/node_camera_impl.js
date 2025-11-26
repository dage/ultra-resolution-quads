const fs = require('fs');
const path = require('path');

// Read input from stdin
let data = '';
process.stdin.on('data', chunk => {
    data += chunk;
});

process.stdin.on('end', () => {
    const input = JSON.parse(data);
    
    // Simulate frontend logic
    const t = input.t;
    const k1 = input.k1;
    const k2 = input.k2;
    
    // --- LOGIC FROM main.js (Simplified/Copied) ---
    const l1 = k1.level;
    const l2 = k2.level;
    const lt = l1 + (l2 - l1) * t;
    const level = Math.floor(lt);
    const zoomOffset = lt - level;
    
    const factor1 = 1.0 / Math.pow(2, l1);
    const gx1 = (k1.tileX + k1.offsetX) * factor1;
    const gy1 = (k1.tileY + k1.offsetY) * factor1;
    
    const factor2 = 1.0 / Math.pow(2, l2);
    const gx2 = (k2.tileX + k2.offsetX) * factor2;
    const gy2 = (k2.tileY + k2.offsetY) * factor2;
    
    const gxt = gx1 + (gx2 - gx1) * t;
    const gyt = gy1 + (gy2 - gy1) * t;
    
    const factorT = Math.pow(2, level);
    const fullX = gxt * factorT;
    const fullY = gyt * factorT;
    
    const tileX = Math.floor(fullX);
    const tileY = Math.floor(fullY);
    const offsetX = fullX % 1; // Note: JS % can be different for neg, but here pos
    const offsetY = fullY % 1;
    // ----------------------------------------------
    
    const result = {
        level,
        zoomOffset,
        tileX,
        tileY,
        offsetX,
        offsetY,
        globalX: gxt,
        globalY: gyt
    };
    
    console.log(JSON.stringify(result));
});
