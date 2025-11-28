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

  // --- 1. Coordinate Math ---

  const toGlobal = (k) => {
    // Standard Global (0..1) + Level
    const limit = Math.pow(2, k.level);
    const gx = (k.tileX + k.offsetX) / limit;
    const gy = (k.tileY + k.offsetY) / limit;
    const totalLevel = k.level + (k.zoomOffset || 0);
    
    return { x: gx, y: gy, level: totalLevel };
  };

  const fromGlobal = (g) => {
    const integerLevel = Math.floor(g.level);
    const limit = Math.pow(2, integerLevel);
    
    const absoluteX = g.x * limit;
    const absoluteY = g.y * limit;

    const tileX = Math.floor(absoluteX);
    const tileY = Math.floor(absoluteY);

    return {
      level: integerLevel,
      tileX: tileX,
      tileY: tileY,
      offsetX: absoluteX - tileX,
      offsetY: absoluteY - tileY,
      globalX: g.x,
      globalY: g.y,
      globalLevel: g.level,
      zoomOffset: g.level - integerLevel
    };
  };

  const visualDist = (p1, p2) => {
    const l_avg = (p1.level + p2.level) / 2;
    const scale = Math.pow(2, l_avg);
    
    const dx = (p1.x - p2.x) * scale;
    const dy = (p1.y - p2.y) * scale;
    const dl = (p1.level - p2.level) * ZOOM_WEIGHT; 
    
    return Math.sqrt(dx * dx + dy * dy + dl * dl);
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
              
              dense.push(fromGlobal({ x: gx_t, y: gy_t, level: l_t }));
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

      this.buildLUT();
    }

    buildLUT() {
      this.lut = [{ dist: 0, t: 0 }];
      this.totalLength = 0;
      const STEPS = 5000; 
      let prevP = { 
        x: this.splineX.at(0), 
        y: this.splineY.at(0), 
        level: this.splineL.at(0) 
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
          level: this.splineL.at(t)
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
            level: this.splineL.at(0)
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
        level: this.splineL.at(t)
      };

      return fromGlobal(g);
    }
  }

  function buildSampler(path, opts = {}) {
    const keyframes = path.keyframes || [];
    if (keyframes.length < 2) {
        const k = keyframes[0] ? (keyframes[0].camera || keyframes[0]) : null;
        return { cameraAtProgress: () => k, pointAtProgress: () => k };
    }

    let normalized = keyframes.map(k => {
        const cam = k.camera || k;
        return { ...cam };
    });

    // Densify to fix geometry and speed
    normalized = densifyPath(normalized);

    const sampler = new PathSampler(normalized);

    return {
      cameraAtProgress: (p) => sampler.getPointAtProgress(p),
      pointAtProgress: (p) => sampler.getPointAtProgress(p),
      sampler: sampler
    };
  }

  return { buildSampler };
});