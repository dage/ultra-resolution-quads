/**
 * Shared Camera Path Sampler (Frontend + Backend)
 * 
 * Strategy: "Filleted Linear Path with Width-Interpolation & Arc-Length Parameterization"
 * 
 * 1. GEOMETRY: The path is defined by Linear Segments connected by Quadratic Bezier corners.
 *    - This ensures robust behavior (no overshoot) in Deep Zooms.
 *    - "Deep Zoom" segments use a special "Swoop" interpolation (linear in Width, not Level)
 *      to prevent astronomical visual path lengths.
 *    - Corners are "Filleted" (cut) to provide C1 smoothness without stopping.
 * 
 * 2. TIMING: The path is re-parameterized by "Visual Distance" (Arc-Length).
 *    - We sample the geometry into a high-resolution Lookup Table (LUT).
 *    - Playback uses the LUT to ensure constant visual velocity relative to the viewport.
 */

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        // Node.js
        const Decimal = require('./libs/decimal.min.js');
        module.exports = factory(Decimal);
    } else {
        // Browser
        root.CameraPath = factory(root.Decimal);
    }
}(typeof self !== 'undefined' ? self : this, function(Decimal) {

    // --- Configuration ---
    
    const CONFIG = {
        // Precision sufficient for ~Level 100+
        DECIMAL_PRECISION: 50,
        
        // Corner Logic
        CORNER_RATIO: 0.5,        // 0.5 = Max curvature (starts halfway through segment)
        MAX_CORNER_RADIUS: 4.0,   // Cap turn radius to ~4 screen widths to prevent "Orbiting" behavior at deep levels
        
        // Sampling
        SAMPLES_PER_PRIM: 2000,   // High LUT resolution to prevent velocity quantization noise
        
        // Deep Zoom Thresholds
        DEEP_ZOOM_RATIO: 100,     // Visual/Euclidean ratio to trigger Deep Zoom logic
        MICRO_PAN_LIMIT: 1e-4     // Max Euclidean distance to still consider "Microscopic" (Linear/Swoop only)
    };

    Decimal.set({ precision: CONFIG.DECIMAL_PRECISION });

    // --- Helpers ---

    const clamp01 = (v) => {
        if (v.lessThan(0)) return new Decimal(0);
        if (v.greaterThan(1)) return new Decimal(1);
        return v;
    };

    // Converts generic camera object to canonical Decimal format
    const normalizeCamera = (cam) => {
        if (!cam || typeof cam !== 'object') return cam;
        
        let globalLevel = 0;
        if (typeof cam.globalLevel === 'number') {
            globalLevel = cam.globalLevel;
        } else {
            const lvl = typeof cam.level === 'number' ? cam.level : 0;
            const off = typeof cam.zoomOffset === 'number' ? cam.zoomOffset : 0;
            globalLevel = lvl + off;
        }

        const toDec = (val) => {
            if (val instanceof Decimal) return val;
            if (typeof val === 'number' || typeof val === 'string') return new Decimal(val);
            return new Decimal(0.5);
        };

        return {
            globalLevel: globalLevel,
            x: clamp01(toDec(cam.x)),
            y: clamp01(toDec(cam.y)),
            rotation: typeof cam.rotation === 'number' ? cam.rotation : 0
        };
    };

    // --- Metrics ---

    // Visual Distance: The "Perceptual" distance metric used for constant-speed timing.
    // Approximates the flow of pixels on screen.
    const visualDist = (p1, p2) => {
        const l_ref = Math.min(p1.globalLevel, p2.globalLevel);
        
        let dx, dy;

        // Optimization: Use native Math.pow for levels < 1000
        // Fallback to Decimal.pow for >= 1000 to support extreme zoom levels
        if (Math.abs(l_ref) < 1000) {
            const scale = Math.pow(2, l_ref);
            dx = p1.x.minus(p2.x).times(scale).toNumber();
            dy = p1.y.minus(p2.y).times(scale).toNumber();
        } else {
            const scale = Decimal.pow(2, l_ref);
            dx = p1.x.minus(p2.x).times(scale).toNumber();
            dy = p1.y.minus(p2.y).times(scale).toNumber();
        }
        
        const dl = (p1.globalLevel - p2.globalLevel);
        const dr = (p1.rotation - p2.rotation);
        
        return Math.sqrt(dx*dx + dy*dy + dl*dl + dr*dr);
    };

    const euclideanDist = (p1, p2) => {
        const dx = p1.x.minus(p2.x).toNumber();
        const dy = p1.y.minus(p2.y).toNumber();
        return Math.sqrt(dx*dx + dy*dy);
    };

    // --- Primitives ---

    /**
     * Creates a Linear Segment (P1 -> P2).
     * Simplified Strategy: Always prefer Swoop (Geodesic) unless mathematically impossible.
     */
    const createLine = (p1, p2, _ignoredDeepZoomFlag) => {
        // Pre-calculate widths for "Swoop" interpolation
        const two = new Decimal(2);
        const w1 = Decimal.pow(two, -p1.globalLevel);
        const w2 = Decimal.pow(two, -p2.globalLevel);
        const wDelta = w2.minus(w1);

        // Check if we have a valid width change to support Swoop.
        // If wDelta is effectively zero (Pure Pan), we must use Linear to avoid division by zero.
        const canSwoop = !wDelta.isZero();

        return {
            type: 'line',
            p1, p2,
            eval: (t) => { // t in [0, 1]
                // Linearly interpolate non-spatial properties
                // We use Decimal for level interpolation to avoid precision loss when 
                // level difference is tiny (< 1e-15), which would cause 's' to snap to 0 or 1.
                const dL1 = new Decimal(p1.globalLevel);
                const dL2 = new Decimal(p2.globalLevel);
                const dLvl = dL1.plus(dL2.minus(dL1).times(t));
                
                const rot = p1.rotation + (p2.rotation - p1.rotation) * t;
                
                let s = new Decimal(t); 
                
                // UNIFIED LOGIC:
                // If we can swoop, we swoop. This handles Deep Zooms, Shallow Zooms, 
                // and Micro-drifts correctly without arbitrary thresholds.
                if (canSwoop) {
                    const wCurr = Decimal.pow(two, dLvl.negated());
                    s = wCurr.minus(w1).div(wDelta);
                }
                
                const x = p1.x.plus(p2.x.minus(p1.x).times(s));
                const y = p1.y.plus(p2.y.minus(p1.y).times(s));
                
                return { x, y, globalLevel: dLvl.toNumber(), rotation: rot };
            }
        };
    };

    /**
     * Creates a Quadratic Bezier Corner (P0 -> P1 -> P2).
     * P1 is the control point (the original sharp corner).
     * P0 and P2 are the start/end points on the filleted segments.
     */
    const createCorner = (p0, p1, p2) => {
        return {
            type: 'corner',
            p0, p1, p2,
            eval: (t) => { // t in [0, 1]
                const decT = new Decimal(t);
                const one = new Decimal(1);
                const inv = one.minus(decT);
                
                // Basis functions in Decimal
                const b0 = inv.times(inv);
                const b1 = inv.times(decT).times(2);
                const b2 = decT.times(decT);
                
                // Bezier Blend
                const x = p0.x.times(b0).plus(p1.x.times(b1)).plus(p2.x.times(b2));
                const y = p0.y.times(b0).plus(p1.y.times(b1)).plus(p2.y.times(b2));
                
                // Linear Level/Rot (sufficient for now)
                const lvl = p0.globalLevel * b0.toNumber() + p1.globalLevel * b1.toNumber() + p2.globalLevel * b2.toNumber();
                const rot = p0.rotation * b0.toNumber() + p1.rotation * b1.toNumber() + p2.rotation * b2.toNumber();
                
                return { x, y, globalLevel: lvl, rotation: rot };
            }
        };
    };

    // --- Main Sampler Factory ---

    function buildSampler(path) {
        const keyframes = path && Array.isArray(path.keyframes) ? path.keyframes : [];
        const cams = keyframes.map(k => resolveCameraMacros(k.camera || k));

        if (cams.length === 0) return { cameraAtProgress: () => null, pointAtProgress: () => null };
        if (cams.length === 1) {
            const c = cams[0];
            return { cameraAtProgress: () => ({ ...c }), pointAtProgress: () => ({ ...c }), totalLength: 0, stops: [0] };
        }

        // Phase 1: Geometry Generation (Primitives)
        // Convert the list of keyframes into a sequence of Lines and Corners.
        const primitives = [];
        const rawLengths = [];
        const deepZoomFlags = [];

        // Pre-pass: Analyze segments
        for (let i = 0; i < cams.length - 1; i++) {
            let d = visualDist(cams[i], cams[i+1]);
            if (d < 1e-9) d = 1e-9;
            rawLengths.push(d);

            // Detect Deep Zoom conditions
            const eDist = euclideanDist(cams[i], cams[i+1]);
            
            // Use MAX level to detect if we are touching deep levels (Zoom Out support).
            // If we used visualDist (min level), L10->L0 would look like a "shallow" move (Ratio ~20)
            // and fail to trigger Swoop. With Max Level, Ratio is ~20,000.
            const maxLevel = Math.max(cams[i].globalLevel, cams[i+1].globalLevel);
            const maxScale = Decimal.pow(2, maxLevel).toNumber();
            
            // Ratio of "Worst Case Visual Distance" to Euclidean Distance
            // If eDist is tiny, ratio is huge.
            const ratio = (eDist < 1e-9) ? 1e9 : (eDist * maxScale) / eDist; // effectively just maxScale
            
            // Use Swoop logic if the ratio of Visual/Euclidean distance is huge (Deep Zoom).
            // We removed the MICRO_PAN_LIMIT check because even "large" euclidean moves (e.g. 0.05)
            // should use Swoop if the Visual distance is massive (Diagonal Deep Zoom), 
            // otherwise we get astronomical path lengths ($10^13$) and tile explosions.
            const isDeep = (ratio > CONFIG.DEEP_ZOOM_RATIO);
            deepZoomFlags.push(isDeep);
        }

        let currentP = cams[0]; // Start point of next primitive

        for (let i = 0; i < cams.length - 1; i++) {
            const pStart = cams[i];
            const pCorner = cams[i+1];
            const len = rawLengths[i];
            const isDeep = deepZoomFlags[i];
            
            // Final Segment
            if (i === cams.length - 2) {
                primitives.push(createLine(currentP, cams[i+1], isDeep));
                break;
            }
            
            // Corner Generation
            const nextLen = rawLengths[i+1];
            
            // Calculate Radius: Percentage of length, but capped for Deep Pan safety
            let radius = Math.min(len, nextLen) * CONFIG.CORNER_RATIO;
            if (radius > CONFIG.MAX_CORNER_RADIUS) radius = CONFIG.MAX_CORNER_RADIUS;
            
            // Calculate In/Out points on the segments
            const t_in = 1.0 - (radius / len);
            // Note: We use the "Swoop" logic (if applicable) to find the point on the line
            const qIn = createLine(pStart, pCorner, isDeep).eval(t_in);
            
            // Add the incoming Line (Start -> qIn)
            primitives.push(createLine(currentP, qIn, isDeep));
            
            // Calculate Out point on next segment
            const t_out = radius / nextLen;
            const pNext = cams[i+2];
            const isNextDeep = deepZoomFlags[i+1];
            const qOut = createLine(pCorner, pNext, isNextDeep).eval(t_out);
            
            // Add the Corner (qIn -> pCorner -> qOut)
            primitives.push(createCorner(qIn, pCorner, qOut));
            
            // Advance
            currentP = qOut;
        }

        // Phase 2: Arc-Length Parameterization (LUT)
        // Sample the geometry to create a map of Time -> Distance
        const lut = [];
        let totalLength = 0;
        const stops = [0]; 
        
        lut.push({ t: 0, dist: 0 });
        
        primitives.forEach((prim, pIdx) => {
            let prevSample = prim.eval(0);
            
            for (let j = 1; j <= CONFIG.SAMPLES_PER_PRIM; j++) {
                const t = j / CONFIG.SAMPLES_PER_PRIM;
                const currSample = prim.eval(t);
                const d = visualDist(prevSample, currSample);
                totalLength += d;
                
                // Global T: Primitive Index + Local T
                lut.push({ t: pIdx + t, dist: totalLength });
                prevSample = currSample;
            }

            // Record stops for timeline UI (Approximation: End of Primitive)
            // Keyframe i corresponds to the end of the turn at Corner i-1
            if (prim.type === 'corner' || pIdx === primitives.length - 1) {
                stops.push(totalLength);
            }
        });

        // Phase 3: Runtime Evaluator
        const cameraAtProgress = (p) => {
            const p_clamped = Math.min(1, Math.max(0, p));
            const targetDist = p_clamped * totalLength;
            
            // Binary Search LUT
            let low = 0, high = lut.length - 1;
            while (low < high) {
                const mid = (low + high) >>> 1;
                if (lut[mid].dist < targetDist) low = mid + 1;
                else high = mid;
            }
            const idx = low;
            
            if (idx === 0) return primitives[0].eval(0);
            
            const p0 = lut[idx - 1];
            const p1 = lut[idx];
            
            // Interpolate Global T
            const ratio = (targetDist - p0.dist) / (p1.dist - p0.dist || 1e-9);
            const globalT = p0.t + ratio * (p1.t - p0.t);
            
            // Resolve to Primitive + Local T
            let primIdx = Math.floor(globalT);
            let localT = globalT - primIdx;
            
            if (primIdx >= primitives.length) {
                primIdx = primitives.length - 1;
                localT = 1;
            }
            
            const c = primitives[primIdx].eval(localT);
            
            return {
                x: clamp01(c.x),
                y: clamp01(c.y),
                globalLevel: c.globalLevel,
                rotation: c.rotation
            };
        };

        return {
            cameraAtProgress,
            pointAtProgress: cameraAtProgress,
            totalLength: totalLength,
            stops: stops,
            _segments: primitives // Exposed for debugging
        };
    }

    // --- Macro Resolution ---

    const MANDELBROT_BOUNDS = {
        centerRe: new Decimal("-0.75"),
        centerIm: new Decimal("0.0"),
        width: new Decimal("3.0"),
        height: new Decimal("3.0")
    };

    const resolveGlobalMacro = (cam) => {
        if (cam.globalX === undefined || cam.globalY === undefined) return null;
        return normalizeCamera({ ...cam, x: cam.globalX, y: cam.globalY });
    };

    const resolveMandelbrotMacro = (cam) => {
        if (cam.re === undefined || cam.im === undefined) return null;
        const re = new Decimal(cam.re);
        const im = new Decimal(cam.im);
        const { centerRe, centerIm, width, height } = MANDELBROT_BOUNDS;
        const minRe = centerRe.minus(width.div(2));
        const maxIm = centerIm.plus(height.div(2));
        
        // Normalized coordinates
        const gx = re.minus(minRe).div(width);
        const gy = maxIm.minus(im).div(height);
        
        return normalizeCamera({ ...cam, x: gx, y: gy });
    };

    const resolveCameraMacros = (cam) => {
        if (!cam || typeof cam !== 'object') return cam;
        const macro = cam.macro;
        
        if (macro === 'mandelbrot' || macro === 'mandelbrot_point' || macro === 'mb') {
            const res = resolveMandelbrotMacro(cam);
            if (res) return res;
        }
        
        if (macro === 'global' || (cam.globalX !== undefined && cam.globalY !== undefined)) {
            const res = resolveGlobalMacro(cam);
            if (res) return res;
        }
        
        return normalizeCamera(cam);
    };

    const resolvePathMacros = (path) => {
        if (!path || !Array.isArray(path.keyframes)) return path;
        const keyframes = path.keyframes.map(kf => {
            const cam = kf.camera || kf;
            const resolved = resolveCameraMacros(cam);
            return { ...kf, camera: resolved };
        });
        return { ...path, keyframes };
    };

    // Export
    return { buildSampler, resolvePathMacros };
}));
