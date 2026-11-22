/* Offline approximation of what the allowlisted rendering flags change. Port of engine.render_rows.
   It draws a made-up scene; it is not a capture of Roblox and proves nothing about the real client. */
(function () {
  "use strict";

  const DEFAULT = { texture_level: null, texture_downscale: 1, sky_gray: false, grass: true, flat_lighting: false, quality_level: null };

  function hash(x, y) {
    let n = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263)) | 0;
    n = Math.imul(n ^ (n >>> 13), 1274126177);
    return ((n ^ (n >>> 16)) >>> 0) % 100;
  }

  // Wall: bricks with mortar and per-brick tint. Coordinates are in "scene units" (320 wide).
  function wallTex(u, v) {
    const row = Math.floor(v / 10), off = row % 2 ? 11 : 0;
    const bx = Math.floor((u + off) / 22), lu = (u + off) % 22, lv = v % 10;
    if (lu < 1.2 || lv < 1.2) return [172, 166, 156];
    const t = hash(bx, row) / 100, n = hash(Math.floor(u), Math.floor(v)) / 100;
    return [150 + 40 * t + 14 * n, 74 + 18 * t + 10 * n, 58 + 12 * t + 8 * n];
  }
  // Ground: stone tiles.
  function groundTex(u, v) {
    const tu = Math.floor(u / 18), tv = Math.floor(v / 9), lu = u % 18, lv = v % 9;
    if (lu < 1 || lv < 1) return [70, 74, 72];
    const t = hash(tu + 7, tv + 3) / 100, n = hash(Math.floor(u) + 91, Math.floor(v)) / 100;
    return [104 + 22 * t + 10 * n, 108 + 20 * t + 10 * n, 100 + 16 * t + 8 * n];
  }

  function render(canvas, params, opts) {
    const p = Object.assign({}, DEFAULT, params || {});
    const w = canvas.width, h = canvas.height;
    if (!w || !h) return;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(w, h);
    const px = img.data;
    const k = 320 / w;                    // scene units per pixel
    const d = Math.max(1, p.texture_downscale | 0); // block size in scene units
    const horizon = Math.round(h * 0.42);
    const x0 = Math.round(w * 0.2), y0 = Math.round(h * 0.18), x1 = Math.round(w * 0.8), y1 = Math.round(h * 0.7);
    const sunX = w * 0.1, sunY = h * 0.12, sunR2 = 90 / (k * k);
    const sh0 = y1, sh1 = y1 + Math.round(10 / k), shx0 = x0 - Math.round(2 / k), shx1 = x1 + Math.round(14 / k);

    // Block-average a texture at scene resolution d: sample the block's cells once.
    const cache = new Map();
    function sample(tex, u, v, key) {
      if (d === 1) return tex(u, v);
      const bu = Math.floor(u / d), bv = Math.floor(v / d), id = key + bu + "," + bv;
      let c = cache.get(id);
      if (!c) {
        c = [0, 0, 0];
        let n = 0;
        for (let j = 0; j < d; j++) for (let i = 0; i < d; i++) {
          const t = tex(bu * d + i, bv * d + j);
          c[0] += t[0]; c[1] += t[1]; c[2] += t[2]; n++;
        }
        c[0] /= n; c[1] /= n; c[2] /= n;
        cache.set(id, c);
      }
      return c;
    }

    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let r, g, b;
        const u = x * k, v = y * k;
        const inWall = x >= x0 && x < x1 && y >= y0 && y < y1;
        if (inWall) {
          [r, g, b] = sample(wallTex, u - x0 * k, v - y0 * k, "w");
        } else if (y < horizon) {
          if (p.sky_gray) { r = g = b = 150; }
          else {
            const t = y / horizon;
            r = 70 + 120 * t; g = 140 + 85 * t; b = 220 + 35 * t;
            const dx = x - sunX, dy = y - sunY;
            if (dx * dx + dy * dy < sunR2) { r = 255; g = 240; b = 185; }
          }
          px.set([r, g, b, 255], (y * w + x) * 4);
          continue;
        } else {
          [r, g, b] = sample(groundTex, u, v, "g");
          if (p.grass && y > horizon + 4 / k && hash(Math.floor(u), Math.floor(v / 4)) < 34) {
            r = 70; g = 150 + hash(Math.floor(u) + 3, Math.floor(v)) % 40; b = 50;
          }
        }
        let s = p.flat_lighting ? 0.9 : 1.08 - 0.42 * x / w;
        if (!inWall && y >= sh0 && y < sh1 && x >= shx0 && x < shx1) s *= 0.58;
        const o = (y * w + x) * 4;
        px[o] = Math.min(255, r * s); px[o + 1] = Math.min(255, g * s); px[o + 2] = Math.min(255, b * s); px[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }

  // Same block averaging, applied to a real image the user picked (Asset Studio).
  function downscaleImage(canvas, image, factor) {
    const w = canvas.width, h = canvas.height, ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.clearRect(0, 0, w, h);
    const s = Math.min(w / image.naturalWidth, h / image.naturalHeight);
    const dw = Math.round(image.naturalWidth * s), dh = Math.round(image.naturalHeight * s);
    const dx = (w - dw) >> 1, dy = (h - dh) >> 1;
    if (factor <= 1) { ctx.drawImage(image, dx, dy, dw, dh); return; }
    // Texture quality drops mip levels: shrink the source by `factor`, then scale back up.
    const tw = Math.max(1, Math.round(image.naturalWidth / factor)), th = Math.max(1, Math.round(image.naturalHeight / factor));
    const tmp = document.createElement("canvas");
    tmp.width = tw; tmp.height = th;
    const tctx = tmp.getContext("2d");
    tctx.imageSmoothingQuality = "high";
    tctx.drawImage(image, 0, 0, tw, th);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(tmp, dx, dy, dw, dh);
  }

  function fromFlags(flags, allow) {
    const f = {};
    for (const [key, v] of Object.entries(flags)) {
      if (!allow.has(key)) continue;
      const s = String(v).trim();
      f[key] = /^(true|false)$/i.test(s) ? (s.toLowerCase() === "true" ? "True" : "False") : s;
    }
    let level = null;
    if (f.DFFlagTextureQualityOverrideEnabled === "True" && "DFIntTextureQualityOverride" in f) {
      level = Math.max(0, Math.min(3, parseInt(f.DFIntTextureQualityOverride, 10) || 0));
    }
    const q = f.DFIntDebugFRMQualityLevelOverride;
    return {
      texture_level: level,
      texture_downscale: { null: 1, 3: 1, 2: 2, 1: 4, 0: 8 }[level],
      sky_gray: f.FFlagDebugSkyGray === "True",
      grass: f.FIntFRMMaxGrassDistance !== "0",
      flat_lighting: f.DFFlagDebugPauseVoxelizer === "True",
      quality_level: q !== undefined ? parseInt(q, 10) : null,
    };
  }

  window.FTPreview = { render, downscaleImage, fromFlags, DEFAULT };
})();
