export const meta = {
  id: 'p36', title: 'Accessibility contrast checker', category: 'Design', version: '1.1.0',
  description: 'Calculate opaque sRGB contrast and compare normal text, large text, and non-text thresholds.',
  example: { foreground: '#777777', background: '#FFFFFF' },
  fields: [{ key: 'foreground', label: 'Foreground hex color', type: 'text' }, { key: 'background', label: 'Background hex color', type: 'text' }]
};
function color(value, label) {
  if (typeof value !== 'string' || !/^#?(?:[\da-fA-F]{3}|[\da-fA-F]{6})$/.test(value)) throw new Error(`${label} must be a 3- or 6-digit hex color`);
  let hex = value.replace('#', '');
  if (hex.length === 3) hex = [...hex].map(c => c + c).join('');
  hex = hex.toUpperCase();
  const channels = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return { hex: `#${hex}`, luminance: 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2] };
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const foreground = color(input.foreground, 'foreground');
  const background = color(input.background, 'background');
  const ratio = (Math.max(foreground.luminance, background.luminance) + 0.05) / (Math.min(foreground.luminance, background.luminance) + 0.05);
  const blackRatio = (background.luminance + 0.05) / 0.05;
  const whiteRatio = 1.05 / (background.luminance + 0.05);
  return {
    foreground: foreground.hex, background: background.hex,
    foregroundLuminance: Number(foreground.luminance.toFixed(6)), backgroundLuminance: Number(background.luminance.toFixed(6)), contrastRatio: Number(ratio.toFixed(2)),
    passes: { aaNormal: ratio >= 4.5, aaaNormal: ratio >= 7, aaLarge: ratio >= 3, aaaLarge: ratio >= 4.5, nonText: ratio >= 3 },
    preferredTextOnBackground: blackRatio >= whiteRatio ? '#000000' : '#FFFFFF'
  };
}
