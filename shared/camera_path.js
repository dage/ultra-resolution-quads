// Shared camera path sampler (frontend + backend via Node).
// Implements C2 Continuous Camera Paths in Quadtree Space using Natural Cubic Splines.

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.CameraPath = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {

  const MAX_LEVEL = 20;
  const ZOOM_WEIGHT = 1.0; 
  const ROTATION_WEIGHT = 1.0;

  // --- 1. Coordinate Math ---
  // Canonical camera: { globalLevel, x, y, rotation }
  // x/y are normalized to [0,1) at level 0. globalLevel is a double (integer + fractional crossfade).

  const clamp01 = (v) => Math.min(1, Math.max(0, v));

  const normalizeCamera = (cam) => {
    if (!cam || typeof cam !== 'object') return cam;
    const globalLevel = typeof cam.globalLevel === 'number'
      ? cam.globalLevel
      : (cam.level || 0) + (cam.zoomOffset || 0);

    // Preferred: x/y already provided
    if (typeof cam.x === 'number' && typeof cam.y === 'number') {
      return {
        globalLevel,
        x: clamp01(cam.x),
        y: clamp01(cam.y),
        rotation: cam.rotation || 0
      };
    }

    // Legacy: globalX/globalY
    if (typeof cam.globalX === 'number' && typeof cam.globalY === 'number') {
      return {
        globalLevel,
        x: clamp01(cam.globalX),
        y: clamp01(cam.globalY),
        rotation: cam.rotation || 0
      };
    }

    // Fallback to origin
    return { globalLevel, x: 0.5, y: 0.5, rotation: cam.rotation || 0 };
  };

  const toGlobal = (k) => {
    const cam = normalizeCamera(k);
    return { x: cam.x, y: cam.y, level: cam.globalLevel, rotation: cam.rotation };
  };

  const fromGlobal = (g) => {
    const integerLevel = Math.floor(g.level);
    return {
      globalLevel: g.level,
      x: clamp01(g.x),
      y: clamp01(g.y),
      rotation: g.rotation || 0,
      globalX: clamp01(g.x),
      globalY: clamp01(g.y),
      globalLevel: g.level
    };
  };

  // --- 0. Path Macros ---
  const resolveGlobalMacro = (cam) => {
    if (typeof cam.globalX !== 'number' || typeof cam.globalY !== 'number') {
      return null;
    }
    const g = fromGlobal({
      x: clamp01(cam.globalX),
      y: clamp01(cam.globalY),
      level: cam.globalLevel || (cam.level || 0) + (cam.zoomOffset || 0),
      rotation: cam.rotation || 0
    });
    return { ...cam, ...g, macro: undefined };
  };

  const MANDELBROT_BOUNDS = {
    centerRe: -0.75,
    centerIm: 0.0,
    width: 3.0,
    height: 3.0
  };

  const resolveMandelbrotMacro = (cam) => {
    if (typeof cam.re !== 'number' || typeof cam.im !== 'number') {
      return null;
    }
    const { centerRe, centerIm, width, height } = MANDELBROT_BOUNDS;
    const minRe = centerRe - width / 2;
    const maxIm = centerIm + height / 2;
    const gx = clamp01((cam.re - minRe) / width);
    const gy = clamp01((maxIm - cam.im) / height); // invert because tileY grows downward
    const g = fromGlobal({
      x: gx,
      y: gy,
      level: cam.globalLevel || (cam.level || 0) + (cam.zoomOffset || 0),
      rotation: cam.rotation || 0
    });
    return { ...cam, ...g, macro: undefined };
  };

  const resolveCameraMacros = (cam) => {
    if (!cam || typeof cam !== 'object') return cam;
    const macro = cam.macro;
    if (macro === 'global' || (cam.globalX !== undefined && cam.globalY !== undefined)) {
      const res = resolveGlobalMacro(cam);
      if (res) return normalizeCamera(res);
    }
    if (macro === 'mandelbrot' || macro === 'mandelbrot_point' || macro === 'mb') {
      const res = resolveMandelbrotMacro(cam);
      if (res) return normalizeCamera(res);
    }
    return normalizeCamera(cam);
  };

  const visualDist = (p1, p2) => {
    const l_avg = (p1.level + p2.level) / 2;
    const scale = Math.pow(2, l_avg);
    
    const dx = (p1.x - p2.x) * scale;
    const dy = (p1.y - p2.y) * scale;
    const dl = (p1.level - p2.level) * ZOOM_WEIGHT; 
    const dr = ((p1.rotation || 0) - (p2.rotation || 0)) * ROTATION_WEIGHT;
    
    return Math.sqrt(dx * dx + dy * dy + dl * dl + dr * dr);
  };

  // --- 2. Densification (The Fix) ---
  
  function densifyPath(keyframes) {
      if (keyframes.length < 2) return keyframes;
      
      const dense = [];
      
      for (let i = 0; i < keyframes.length - 1; i++) {
          const k1 = keyframes[i];
          const k2 = keyframes[i+1];
          
          const p1 = toGlobal(k1);
          const p2 = toGlobal(k2);
          
          const w1 = Math.pow(2, p1.level);
          const w2 = Math.pow(2, p2.level);
          
          // Calculate steps based on Level difference (at least 20 per level, min 50)
          const dl = Math.abs(p1.level - p2.level);
          
          // OPTIMIZATION: For pure panning or shallow zooms, skip densification.
          // This allows the Natural Cubic Spline to curve smoothly around corners (C2 continuity),
          // preserving the "fly-through" feel for exploration paths.
          // For deep zooms (dl >= 4.0), we densify to enforce the "Target Lock" geometry.
          if (dl < 4.0) {
              dense.push(keyframes[i]);
              continue;
          }
          
          const steps = Math.max(50, Math.ceil(dl * 20));
          
          for (let s = 0; s < steps; s++) {
              const t = s / steps;
              
              // Linear Interpolation of Level (Visual Speed)
              const l_t = p1.level + t * (p2.level - p1.level);
              const w_t = Math.pow(2, l_t);
              const r_t = (p1.rotation || 0) + t * ((p2.rotation || 0) - (p1.rotation || 0));

              // Projective Interpolation of Position (Geometry)
              let alpha;
              if (Math.abs(w2 - w1) < 1e-9) {
                  alpha = t; // Pan only
              } else {
                  alpha = (w_t - w1) / (w2 - w1);
              }
              
              const h1x = p1.x * w1;
              const h1y = p1.y * w1;
              
              const h2x = p2.x * w2;
              const h2y = p2.y * w2;
              
              const htx = h1x * (1 - alpha) + h2x * alpha;
              const hty = h1y * (1 - alpha) + h2y * alpha;
              const htw = w1 * (1 - alpha) + w2 * alpha;
              
              // Project back
              const gx_t = htx / htw;
              const gy_t = hty / htw;
          
              dense.push(fromGlobal({ x: gx_t, y: gy_t, level: l_t, rotation: r_t }));
          }
      }
      dense.push(keyframes[keyframes.length - 1]);
      return dense;
  }

  // --- 3. Splines & Sampler (Standard Cartesian) ---

  class Spline1D {
    constructor(xs, ys) {
      this.xs = xs;
      this.ys = ys;
      const n = xs.length - 1;
      
      const a = new Float64Array(n);
      const b = new Float64Array(n);
      const c = new Float64Array(n);
      const r = new Float64Array(n + 1);

      const h = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        h[i] = xs[i + 1] - xs[i];
      }

      for (let i = 1; i < n; i++) {
        a[i] = h[i - 1] / 6;
        b[i] = (h[i - 1] + h[i]) / 3;
        c[i] = h[i] / 6;
        r[i] = (ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1];
      }

      const c_prime = new Float64Array(n);
      const d_prime = new Float64Array(n);

      if (n > 0 && b[1] !== 0) {
        c_prime[1] = c[1] / b[1];
        d_prime[1] = r[1] / b[1];

        for (let i = 2; i < n; i++) {
          const temp = b[i] - a[i] * c_prime[i - 1];
          c_prime[i] = c[i] / temp;
          d_prime[i] = (r[i] - a[i] * d_prime[i - 1]) / temp;
        }
      }

      this.m = new Array(n + 1).fill(0);
      if (n > 0) {
        for (let i = n - 1; i >= 1; i--) {
          this.m[i] = d_prime[i] - c_prime[i] * this.m[i + 1];
        }
      }
    }

    at(x) {
      let i = this.xs.length - 2;
      if (i < 0) i = 0; 
      let low = 0, high = this.xs.length - 2;
      while (low <= high) {
        const mid = (low + high) >>> 1;
        if (this.xs[mid] <= x && x <= this.xs[mid+1]) {
            i = mid; break;
        } else if (this.xs[mid] > x) {
            high = mid - 1;
        } else {
            low = mid + 1;
        }
      }
      if (x < this.xs[0]) i = 0;
      if (x > this.xs[this.xs.length - 1]) i = this.xs.length - 2;
      if (i < 0) i = 0;

      const h = this.xs[i + 1] - this.xs[i];
      if (h === 0) return this.ys[i];

      const a = (this.xs[i + 1] - x) / h;
      const b = (x - this.xs[i]) / h;

      return a * this.ys[i] + b * this.ys[i + 1] + 
             ((a * a * a - a) * this.m[i] + (b * b * b - b) * this.m[i + 1]) * (h * h) / 6;
    }
  }

  class PathSampler {
    constructor(keyframes) {
      const points = keyframes.map(toGlobal);
      
      this.keyframeTimes = [0];
      let currentTime = 0;
      for (let i = 1; i < points.length; i++) {
        const d = visualDist(points[i], points[i-1]);
        currentTime += d;
        this.keyframeTimes.push(currentTime);
      }
      this.maxTime = currentTime;

      this.splineX = new Spline1D(this.keyframeTimes, points.map(p => p.x));
      this.splineY = new Spline1D(this.keyframeTimes, points.map(p => p.y));
      this.splineL = new Spline1D(this.keyframeTimes, points.map(p => p.level));
      this.splineR = new Spline1D(this.keyframeTimes, points.map(p => p.rotation || 0));

      this.buildLUT();
    }

    buildLUT() {
      this.lut = [{ dist: 0, t: 0 }];
      this.totalLength = 0;
      const STEPS = 5000; 
      let prevP = { 
        x: this.splineX.at(0), 
        y: this.splineY.at(0), 
        level: this.splineL.at(0),
        rotation: this.splineR.at(0)
      };

      if (this.maxTime <= 1e-9) {
        this.lut.push({ dist: 0, t: 0 });
        this.keyframeProgresses = this.keyframeTimes.map(() => 0);
        return;
      }

      for (let i = 1; i <= STEPS; i++) {
        const t = (i / STEPS) * this.maxTime;
        const currP = {
          x: this.splineX.at(t),
          y: this.splineY.at(t),
          level: this.splineL.at(t),
          rotation: this.splineR.at(t)
        };
        
        const d = visualDist(prevP, currP);
        this.totalLength += d;
        this.lut.push({ dist: this.totalLength, t: t });
        prevP = currP;
      }

      this.keyframeProgresses = this.keyframeTimes.map(kt => {
         const entry = this.lut.find(e => e.t >= kt);
         return entry && this.totalLength > 0 ? entry.dist / this.totalLength : 0;
      });
    }

    getPointAtProgress(p) {
      if (this.totalLength === 0) {
          const g = {
            x: this.splineX.at(0),
            y: this.splineY.at(0),
            level: this.splineL.at(0),
            rotation: this.splineR.at(0)
          };
          return fromGlobal(g);
      }

      const targetDist = Math.max(0, Math.min(1, p)) * this.totalLength;

      let low = 0, high = this.lut.length - 1, idx = 0;
      while (low <= high) {
        const mid = (low + high) >>> 1;
        if (this.lut[mid].dist >= targetDist) {
          idx = mid;
          high = mid - 1;
        } else {
          low = mid + 1;
        }
      }
      if (idx === 0) idx = 1;
      if (idx >= this.lut.length) idx = this.lut.length - 1;

      const entryA = this.lut[idx - 1];
      const entryB = this.lut[idx];
      
      const distGap = entryB.dist - entryA.dist;
      const ratio = distGap === 0 ? 0 : (targetDist - entryA.dist) / distGap;
      const t = entryA.t + (entryB.t - entryA.t) * ratio;

      const g = {
        x: this.splineX.at(t),
        y: this.splineY.at(t),
        level: this.splineL.at(t),
        rotation: this.splineR.at(t)
      };

      return fromGlobal(g);
    }
  }

  function buildSampler(path, opts = {}) {
    const keyframes = path.keyframes || [];
    let normalized = keyframes.map(k => {
        const cam = k.camera || k;
        const resolved = resolveCameraMacros(cam);
        const { macro, ...rest } = resolved || {};
        return normalizeCamera({ ...rest });
    });

    if (normalized.length < 2) {
        const k = normalized[0] || null;
        return { cameraAtProgress: () => k, pointAtProgress: () => k };
    }

    // Densify to fix geometry and speed
    normalized = densifyPath(normalized);

    const sampler = new PathSampler(normalized);

    return {
      cameraAtProgress: (p) => sampler.getPointAtProgress(p),
      pointAtProgress: (p) => sampler.getPointAtProgress(p),
      sampler: sampler
    };
  }

  function resolvePathMacros(path) {
    if (!path || !Array.isArray(path.keyframes)) return path;
    const keyframes = path.keyframes.map(kf => {
      const cam = kf.camera || kf;
      const resolved = resolveCameraMacros(cam);
      const { macro, ...rest } = resolved || {};
      return { ...kf, camera: normalizeCamera({ ...rest }) };
    });
    return { ...path, keyframes };
  }

  return { buildSampler, resolvePathMacros };
});
