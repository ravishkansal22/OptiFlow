/**
 * Fitting latitude/longitude to an SVG frame.
 *
 * Shared by every map in the app so a point sits in the same place whichever
 * screen draws it. The corridor is far taller than it is wide, so a strictly
 * true-scale drawing wastes most of the frame: the fit allows a bounded amount
 * of anisotropy, which keeps the layout readable without moving points relative
 * to one another beyond recognition.
 */

export interface Projection {
  project: (lat: number, lon: number) => { x: number; y: number };
  height: number;
}

export interface FitOptions {
  width: number;
  pad: number;
  minHeight: number;
  maxHeight: number;
  maxAnisotropy?: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function fitProjection(points: [number, number][], opts: FitOptions): Projection {
  const { width, pad, minHeight, maxHeight, maxAnisotropy = 1.6 } = opts;

  if (!points.length) {
    return { project: () => ({ x: width / 2, y: minHeight / 2 }), height: minHeight };
  }

  const lats = points.map((p) => p[0]);
  const lons = points.map((p) => p[1]);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);

  // Longitude degrees are shorter than latitude degrees away from the equator.
  const midLat = (minLat + maxLat) / 2;
  const lonScale = Math.cos((midLat * Math.PI) / 180);

  const spanLat = Math.max(maxLat - minLat, 1e-6);
  const spanLon = Math.max((maxLon - minLon) * lonScale, 1e-6);

  const height = clamp((width * (spanLat / spanLon)) / maxAnisotropy, minHeight, maxHeight);
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;

  const fitX = innerW / spanLon;
  const fitY = innerH / spanLat;
  const base = Math.min(fitX, fitY);
  const scaleX = Math.min(fitX, base * maxAnisotropy);
  const scaleY = Math.min(fitY, base * maxAnisotropy);

  const offsetX = pad + (innerW - spanLon * scaleX) / 2;
  const offsetY = pad + (innerH - spanLat * scaleY) / 2;

  return {
    height,
    project: (lat: number, lon: number) => ({
      x: offsetX + (lon - minLon) * lonScale * scaleX,
      y: offsetY + (maxLat - lat) * scaleY,
    }),
  };
}
