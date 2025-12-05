// Shared camera path sampler (frontend + backend via Node).
// Simplified to straight linear interpolation between keyframes.

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        // Node.js: Require vendored file relative to this file
        const Decimal = require('./libs/decimal.min.js');
        module.exports = factory(Decimal);
    } else {
        // Browser: Expect global dependency
        root.CameraPath = factory(root.Decimal);
    }
}(typeof self !== 'undefined' ? self : this, function(Decimal) {

  // Set default precision.
  // 50 is sufficient for Level 100+ (10^-30). 
  // For Deep Zooms (> Level 100), applications should increase this via Decimal.set().
  Decimal.set({ precision: 50 });

  const clamp01 = (v) => {
      if (v.lessThan(0)) return new Decimal(0);
      if (v.greaterThan(1)) return new Decimal(1);
      return v;
  };

  /**
   * Centralizes all coordinate conversion logic.
   * Input: Object with various possible coordinate properties.
   * Output: Canonical { x, y, globalLevel, rotation } where x,y are Decimals.
   */
  const normalizeCamera = (cam) => {
    if (!cam || typeof cam !== 'object') return cam;

    // 1. Calculate Global Level
    // Priority: globalLevel > (level + zoomOffset) > level > 0
    let globalLevel = 0;
    if (typeof cam.globalLevel === 'number') {
      globalLevel = cam.globalLevel;
    } else {
      const lvl = typeof cam.level === 'number' ? cam.level : 0;
      const off = typeof cam.zoomOffset === 'number' ? cam.zoomOffset : 0;
      globalLevel = lvl + off;
    }

    // 2. Calculate X / Y
    // Strict mode: only accepts canonical 'x' and 'y' or their macros.
    // We assume macros have been resolved before calling this if mixed.
    // But here we convert valid inputs to Decimal.
    
    let x, y;
    
    // Helper to ensure Decimal
    const toDec = (val, def) => {
        if (val instanceof Decimal) return val;
        if (typeof val === 'number' || typeof val === 'string') return new Decimal(val);
        return new Decimal(def);
    };

    x = toDec(cam.x, 0.5);
    y = toDec(cam.y, 0.5);

    return {
      globalLevel: globalLevel,
      x: clamp01(x),
      y: clamp01(y),
      rotation: typeof cam.rotation === 'number' ? cam.rotation : 0
    };
  };

  // --- Path Macros ---
  const MANDELBROT_BOUNDS = {
    centerRe: new Decimal("-0.75"),
    centerIm: new Decimal("0.0"),
    width: new Decimal("3.0"),
    height: new Decimal("3.0")
  };

  const resolveGlobalMacro = (cam) => {
    // Check for existence to be safe.
    if (cam.globalX === undefined || cam.globalY === undefined) return null;
    
    // Explicitly map global coordinates to x/y to ensure they take precedence
    return normalizeCamera({
      ...cam,
      x: cam.globalX,
      y: cam.globalY
    });
  };

  const resolveMandelbrotMacro = (cam) => {
    if (cam.re === undefined || cam.im === undefined) return null;
    
    const re = new Decimal(cam.re);
    const im = new Decimal(cam.im);
    
    const { centerRe, centerIm, width, height } = MANDELBROT_BOUNDS;
    const minRe = centerRe.minus(width.div(2));
    const maxIm = centerIm.plus(height.div(2));
    
    // Calculate normalized coordinates
    // gx = (re - minRe) / width
    const gx = re.minus(minRe).div(width);
    // gy = (maxIm - im) / height (invert because tileY grows downward)
    const gy = maxIm.minus(im).div(height);

    // Construct a temporary object to feed into normalizeCamera
    return normalizeCamera({
      ...cam,
      x: gx,
      y: gy
    });
  };

  const resolveCameraMacros = (cam) => {
    if (!cam || typeof cam !== 'object') return cam;
    const macro = cam.macro;
    
    if (macro === 'mandelbrot' || macro === 'mandelbrot_point' || macro === 'mb') {
      const res = resolveMandelbrotMacro(cam);
      if (res) return res;
    }
    
    // Explicit global macro or implied by globalX/Y
    if (macro === 'global' || (cam.globalX !== undefined && cam.globalY !== undefined)) {
      const res = resolveGlobalMacro(cam);
      if (res) return res;
    }
    
    return normalizeCamera(cam);
  };

  const visualDist = (p1, p2) => {
    // Use the minimum level for scale to approximate the visual distance 
    // of the pan, assuming an optimal "Zoom then Pan" or "Pan then Zoom" 
    // trajectory (hyperbolic) which performs lateral movement at the coarsest level.
    // Using average level (linear midpoint) overestimates distance wildly for deep zooms.
    const l_ref = Math.min(p1.globalLevel, p2.globalLevel);
    // Scale = 2^l_ref
    const scale = Decimal.pow(2, l_ref);
    
    // dx = (p1.x - p2.x) * scale
    const dx = p1.x.minus(p2.x).times(scale);
    const dy = p1.y.minus(p2.y).times(scale);
    
    // Convert to number for distance calculation (we don't need 1000 digits for distance metric)
    const dx_n = dx.toNumber();
    const dy_n = dy.toNumber();
    const dl = (p1.globalLevel - p2.globalLevel);
    const dr = (p1.rotation - p2.rotation);

    return Math.sqrt(dx_n * dx_n + dy_n * dy_n + dl * dl + dr * dr);
  };

  function buildSampler(path) {
    const keyframes = path && Array.isArray(path.keyframes) ? path.keyframes : [];
    const cams = keyframes.map(k => resolveCameraMacros(k.camera || k));

    if (cams.length === 0) {
      return { cameraAtProgress: () => null, pointAtProgress: () => null };
    }
    if (cams.length === 1) {
      const c = cams[0];
      return { cameraAtProgress: () => ({ ...c }), pointAtProgress: () => ({ ...c }) };
    }

    const cumulative = [0];
    let total = 0;
    for (let i = 1; i < cams.length; i++) {
      const d = visualDist(cams[i - 1], cams[i]);
      total += d;
      cumulative.push(total);
    }

    const interpolate = (a, b, t) => {
      const level = a.globalLevel + (b.globalLevel - a.globalLevel) * t;
      
      // We use Decimal for weights to preserve precision during interpolation
      const w1 = Decimal.pow(2, a.globalLevel);
      const w2 = Decimal.pow(2, b.globalLevel);
      const w_t = Decimal.pow(2, level);

      let alpha;
      // Check equality with small epsilon, but w1/w2 are Decimals
      if (w2.minus(w1).abs().lessThan(1e-9)) {
        alpha = new Decimal(t); // pure pan
      } else {
        // alpha = (w_t - w1) / (w2 - w1)
        alpha = w_t.minus(w1).div(w2.minus(w1));
      }

      // h1x = a.x * w1
      const h1x = a.x.times(w1);
      const h1y = a.y.times(w1);
      const h2x = b.x.times(w2);
      const h2y = b.y.times(w2);

      // htx = h1x * (1 - alpha) + h2x * alpha
      const oneMinusAlpha = new Decimal(1).minus(alpha);
      const htx = h1x.times(oneMinusAlpha).plus(h2x.times(alpha));
      const hty = h1y.times(oneMinusAlpha).plus(h2y.times(alpha));
      
      // htw = w1 * (1 - alpha) + w2 * alpha
      const htw = w1.times(oneMinusAlpha).plus(w2.times(alpha));

      const x = htw.isZero() ? a.x : htx.div(htw);
      const y = htw.isZero() ? a.y : hty.div(htw);

      return {
        globalLevel: level,
        x: clamp01(x),
        y: clamp01(y),
        rotation: a.rotation + (b.rotation - a.rotation) * t
      };
    };

    const cameraAtProgress = (p) => {
      if (total === 0) return { ...cams[0] };
      // p is standard number 0-1
      let p_clamped = Math.min(1, Math.max(0, p));
      const target = p_clamped * total;

      let idx = cumulative.findIndex(c => c >= target);
      if (idx === -1) idx = cumulative.length - 1;
      if (idx === 0) idx = 1;

      const prevDist = cumulative[idx - 1];
      const segDist = cumulative[idx] - prevDist;
      const t = segDist === 0 ? 0 : (target - prevDist) / segDist;

      return interpolate(cams[idx - 1], cams[idx], t);
    };

    return {
      cameraAtProgress,
      pointAtProgress: cameraAtProgress,
      totalLength: total,
      stops: cumulative
    };
  }

  function resolvePathMacros(path) {
    if (!path || !Array.isArray(path.keyframes)) return path;
    const keyframes = path.keyframes.map(kf => {
      const cam = kf.camera || kf;
      const resolved = resolveCameraMacros(cam);
      return { ...kf, camera: resolved };
    });
    return { ...path, keyframes };
  }

  return { buildSampler, resolvePathMacros };
}));