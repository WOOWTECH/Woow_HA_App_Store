export const meta = {
  id: 'p38', title: 'Coordinate route distance estimator', category: 'Travel', version: '1.1.0',
  description: 'Estimate spherical great-circle route lengths and optional travel time, including closed loops.',
  example: { points: [{ lat: 25.033, lon: 121.5654 }, { lat: 25.0478, lon: 121.517 }, { lat: 25.1024, lon: 121.5485 }], unit: 'km', closedLoop: true, speedKph: 5 },
  fields: [{ key: 'points', label: 'Latitude/longitude points', type: 'json' }, { key: 'unit', label: 'Distance unit', type: 'select', options: ['km', 'mi'] }, { key: 'speedKph', label: 'Optional average speed (km/h)', type: 'number' }]
};
const round = (n, places) => Number(n.toFixed(places));
function distance(a, b) {
  const rad = Math.PI / 180;
  const latitude = (b.lat - a.lat) * rad, longitude = (b.lon - a.lon) * rad;
  const haversine = Math.sin(latitude / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(longitude / 2) ** 2;
  return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, haversine))));
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { points, unit = 'km', closedLoop = false, speedKph } = input;
  if (!Array.isArray(points) || points.length < 2 || points.length > 500) throw new Error('points must contain 2–500 coordinate objects');
  if (unit !== 'km' && unit !== 'mi') throw new Error('unit must be km or mi');
  if (typeof closedLoop !== 'boolean') throw new Error('closedLoop must be boolean');
  if (speedKph !== undefined && (typeof speedKph !== 'number' || !Number.isFinite(speedKph) || speedKph < 0.1 || speedKph > 2000)) throw new Error('speedKph must be a finite number from 0.1 to 2000');
  points.forEach((point, index) => {
    if (!point || typeof point !== 'object' || Array.isArray(point)) throw new Error(`point ${index + 1} must be an object`);
    for (const [key, limit] of [['lat', 90], ['lon', 180]]) {
      if (typeof point[key] !== 'number' || !Number.isFinite(point[key]) || Math.abs(point[key]) > limit) throw new Error(`point ${index + 1} ${key} must be a finite number from ${-limit} to ${limit}`);
    }
  });
  const factor = unit === 'mi' ? 1 / 1.609344 : 1;
  let totalKm = 0;
  const legs = [];
  for (let i = 0; i < points.length - 1 + Number(closedLoop); i++) {
    const next = (i + 1) % points.length;
    const km = distance(points[i], points[next]);
    totalKm += km;
    legs.push({ from: i + 1, to: next + 1, distance: round(km * factor, 3) });
  }
  return { unit, closedLoop, legs, totalDistance: round(totalKm * factor, 3), travelMinutes: speedKph === undefined ? null : round(totalKm / speedKph * 60, 1) };
}
