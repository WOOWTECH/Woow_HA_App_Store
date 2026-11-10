export const meta = {
  id: 'p37', title: 'Color palette RGB/HSL transforms', category: 'Design', version: '1.1.0',
  description: 'Rotate hue, adjust saturation/lightness, and derive a complementary color with RGB and HSL values.',
  example: { color: '#336699', hueShift: 30, saturationDelta: 10, lightnessDelta: 5 },
  fields: [{ key: 'color', label: 'Hex color', type: 'text' }, { key: 'hueShift', label: 'Hue rotation (degrees)', type: 'number' }, { key: 'saturationDelta', label: 'Saturation adjustment (percentage points)', type: 'number' }, { key: 'lightnessDelta', label: 'Lightness adjustment (percentage points)', type: 'number' }]
};
const wrap = h => ((h % 360) + 360) % 360;
const clamp = n => Math.min(100, Math.max(0, n));
const round = n => Number(n.toFixed(2));
function rgbToHsl(rgb) {
  const [r, g, b] = rgb.map(c => c / 255), max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  const l = (max + min) / 2;
  let h = 0, s = 0;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    h = max === r ? 60 * ((g - b) / d) : max === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
  }
  return { h: wrap(h), s: s * 100, l: l * 100 };
}
function hslToRgb({ h, s, l }) {
  h = wrap(h); s /= 100; l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
  const channels = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return channels.map(v => Math.round((v + m) * 255));
}
function encode(rgb) {
  const hsl = rgbToHsl(rgb);
  return { hex: `#${rgb.map(c => c.toString(16).padStart(2, '0')).join('').toUpperCase()}`, rgb, hsl: { h: round(hsl.h), s: round(hsl.s), l: round(hsl.l) } };
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { color, hueShift = 0, saturationDelta = 0, lightnessDelta = 0 } = input;
  if (typeof color !== 'string' || !/^#?(?:[\da-fA-F]{3}|[\da-fA-F]{6})$/.test(color)) throw new Error('color must be a 3- or 6-digit hex color');
  for (const [key, value, limit] of [['hueShift', hueShift, 3600], ['saturationDelta', saturationDelta, 100], ['lightnessDelta', lightnessDelta, 100]]) {
    if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > limit) throw new Error(`${key} must be a finite number from ${-limit} to ${limit}`);
  }
  let hex = color.replace('#', '');
  if (hex.length === 3) hex = [...hex].map(c => c + c).join('');
  const rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
  const hsl = rgbToHsl(rgb);
  const transformedHsl = { h: wrap(hsl.h + hueShift), s: clamp(hsl.s + saturationDelta), l: clamp(hsl.l + lightnessDelta) };
  return { original: encode(rgb), transformed: encode(hslToRgb(transformedHsl)), complementary: encode(hslToRgb({ ...transformedHsl, h: wrap(transformedHsl.h + 180) })) };
}
