// Shared camera path sampler (frontend + backend via Node).
// Simplified to straight linear interpolation between keyframes.

(function(root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.CameraPath = factory();
    }
}(typeof self !== 'undefined' ? self : this, function() {

  const clamp01 = (v) => Math.min(1, Math.max(0, v));

  /**
   * Centralizes all coordinate conversion logic.
   * Input: Object with various possible coordinate properties.
   * Output: Canonical { x, y, globalLevel, rotation }
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
    // Priority: x/y > globalX/globalY > 0.5
    let x = 0.5;
    let y = 0.5;

    if (typeof cam.x === 'number') {
      x = cam.x;
    } else if (typeof cam.globalX === 'number') {
      x = cam.globalX;
    }

    if (typeof cam.y === 'number') {
      y = cam.y;
    } else if (typeof cam.globalY === 'number') {
      y = cam.globalY;
    }

    return {
      globalLevel: globalLevel,
      x: clamp01(x),
      y: clamp01(y),
      rotation: typeof cam.rotation === 'number' ? cam.rotation : 0
    };
  };

  // --- Path Macros ---
  const MANDELBROT_BOUNDS = {
    centerRe: -0.75,
    centerIm: 0.0,
    width: 3.0,
    height: 3.0
  };

  const resolveGlobalMacro = (cam) => {
    // This is essentially a pass-through to normalizeCamera since it handles globalX/Y
    // But we check for existence to be safe.
    if (typeof cam.globalX !== 'number' || typeof cam.globalY !== 'number') return null;
    return normalizeCamera(cam);
  };

  const resolveMandelbrotMacro = (cam) => {
    if (typeof cam.re !== 'number' || typeof cam.im !== 'number') return null;
    const { centerRe, centerIm, width, height } = MANDELBROT_BOUNDS;
    const minRe = centerRe - width / 2;
    const maxIm = centerIm + height / 2;
    
    // Calculate normalized coordinates
    const gx = (cam.re - minRe) / width;
    const gy = (maxIm - cam.im) / height; // invert because tileY grows downward

    // Construct a temporary object to feed into normalizeCamera
    // We preserve other props like level/zoomOffset/rotation
    return normalizeCamera({
      ...cam,
      x: gx,
      y: gy
      // globalX/Y are ignored by normalizeCamera if x/y are present
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
    const l_avg = (p1.globalLevel + p2.globalLevel) / 2;
    const scale = Math.pow(2, l_avg);
    const dx = (p1.x - p2.x) * scale;
    const dy = (p1.y - p2.y) * scale;
    const dl = (p1.globalLevel - p2.globalLevel);
    const dr = (p1.rotation - p2.rotation); // rotation is guaranteed 0 if undefined by normalize
    return Math.sqrt(dx * dx + dy * dy + dl * dl + dr * dr);
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
      const w1 = Math.pow(2, a.globalLevel);
      const w2 = Math.pow(2, b.globalLevel);
      const w_t = Math.pow(2, level);

      let alpha;
      if (Math.abs(w2 - w1) < 1e-9) {
        alpha = t; // pure pan
      } else {
        alpha = (w_t - w1) / (w2 - w1);
      }

      const h1x = a.x * w1;
      const h1y = a.y * w1;
      const h2x = b.x * w2;
      const h2y = b.y * w2;

      const htx = h1x * (1 - alpha) + h2x * alpha;
      const hty = h1y * (1 - alpha) + h2y * alpha;
      const htw = w1 * (1 - alpha) + w2 * alpha;

      const x = htw === 0 ? a.x : htx / htw;
      const y = htw === 0 ? a.y : hty / htw;

      return {
        globalLevel: level,
        x: clamp01(x),
        y: clamp01(y),
        rotation: a.rotation + (b.rotation - a.rotation) * t
      };
    };

    const cameraAtProgress = (p) => {
      if (total === 0) return { ...cams[0] };
      const target = clamp01(p) * total;

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
      pointAtProgress: cameraAtProgress
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