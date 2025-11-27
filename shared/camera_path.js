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
  const ZOOM_WEIGHT = 1.0; // Weighting for Level changes vs Pan changes

  // --- 1. Coordinate Math ---

  const toGlobal = (k) => {
    const scale = 1 / Math.pow(2, k.level);
    return {
      x: (k.tileX + k.offsetX) * scale,
      y: (k.tileY + k.offsetY) * scale,
      z: k.level / MAX_LEVEL,
    };
  };

  const fromGlobal = (g) => {
    const level = g.z * MAX_LEVEL;
    const integerLevel = Math.floor(level);
    const scale = Math.pow(2, integerLevel);
    
    const absoluteX = g.x * scale;
    const absoluteY = g.y * scale;

    const tileX = Math.floor(absoluteX);
    const tileY = Math.floor(absoluteY);

    // Ensure we don't return negative offsets due to precision
    let offsetX = absoluteX - tileX;
    let offsetY = absoluteY - tileY;
    
    return {
      level: integerLevel,
      tileX: tileX,
      tileY: tileY,
      offsetX: offsetX,
      offsetY: offsetY,
      globalX: g.x,
      globalY: g.y,
      globalLevel: level,
      zoomOffset: level - integerLevel
    };
  };

  // VISUAL DISTANCE METRIC
  // Calculates distance in "Visual Units" (approx. screen widths) rather than Global Units.
  // This ensures that moving 1 screen width at Level 20 takes the same time as 1 screen width at Level 0.
  const visualDist = (p1, p2) => {
    const l1 = p1.z * MAX_LEVEL;
    const l2 = p2.z * MAX_LEVEL;
    const l_avg = (l1 + l2) / 2;
    
    // The scale at the average level.
    // Scale = 2^L. (Reciprocal of the world-to-viewport factor).
    // Actually: Viewport Width in Global Units = 1 / 2^L.
    // So 1 Global Unit = 2^L Viewport Units.
    const scale = Math.pow(2, l_avg);
    
    const dx = (p1.x - p2.x) * scale;
    const dy = (p1.y - p2.y) * scale;
    const dl = (l1 - l2) * ZOOM_WEIGHT; 
    
    return Math.sqrt(dx * dx + dy * dy + dl * dl);
  };

  // --- 2. The Solver (Natural Cubic Spline) ---

  /**
   * 1D Natural Cubic Spline Interpolator
   */
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
            i = mid;
            break;
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

  // --- 3. The Sampler (Orchestrator) ---

  class PathSampler {
    constructor(keyframes) {
      const points = keyframes.map(toGlobal);
      
      // 1. Parameterization using VISUAL DISTANCE
      this.keyframeTimes = [0];
      let currentTime = 0;
      for (let i = 1; i < points.length; i++) {
        const d = visualDist(points[i], points[i-1]);
        currentTime += d;
        this.keyframeTimes.push(currentTime);
      }
      this.maxTime = currentTime;

      // 2. Build Natural Splines
      this.splineX = new Spline1D(this.keyframeTimes, points.map(p => p.x));
      this.splineY = new Spline1D(this.keyframeTimes, points.map(p => p.y));
      this.splineZ = new Spline1D(this.keyframeTimes, points.map(p => p.z));

      // 3. Build Arc-Length LUT for constant VISUAL speed
      this.buildLUT();
    }

    buildLUT() {
      this.lut = [{ dist: 0, t: 0 }];
      this.totalLength = 0;
      
      const STEPS = 5000; 
      let prevP = { 
        x: this.splineX.at(0), 
        y: this.splineY.at(0), 
        z: this.splineZ.at(0) 
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
          z: this.splineZ.at(t)
        };
        
        // Use visualDist here too so that equal LUT steps = equal visual change
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
            z: this.splineZ.at(0)
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
        z: this.splineZ.at(t)
      };

      return fromGlobal(g);
    }

    getKeyframeIndexForProgress(p) {
      let bestIdx = 0;
      let minDiff = 1000;
      this.keyframeProgresses.forEach((kp, i) => {
        const diff = Math.abs(kp - p);
        if (diff < minDiff) {
          minDiff = diff;
          bestIdx = i;
        }
      });
      return bestIdx; // Return 0-based index
    }
  }

  // --- Export Wrapper ---

  function buildSampler(path, opts = {}) {
    const keyframes = path.keyframes || [];
    
    if (keyframes.length < 2) {
      const k = keyframes[0] ? (keyframes[0].camera || keyframes[0]) : null;
      return {
        cameraAtProgress: () => k,
        pointAtProgress: () => k
      };
    }

    const normalized = keyframes.map(k => k.camera || k);
    const sampler = new PathSampler(normalized);

    return {
      cameraAtProgress: (p) => sampler.getPointAtProgress(p),
      pointAtProgress: (p) => sampler.getPointAtProgress(p),
      sampler: sampler
    };
  }

  return { buildSampler };
});