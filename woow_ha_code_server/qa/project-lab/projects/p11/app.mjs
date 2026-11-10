// Self-contained validation; all application inputs are bounded JSON data.
function object(value, path, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${path} must be an object`);
  for (const key of Object.keys(value)) if (!keys.includes(key)) throw new Error(`${path}.${key} is not a supported field`);
  return value;
}
function array(value, path, min = 0, max = 200) {
  if (!Array.isArray(value) || value.length < min || value.length > max) throw new Error(`${path} must be an array with ${min}..${max} entries`);
  return value;
}
function string(value, path, max = 80) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`${path} must be a nonempty string of at most ${max} characters`);
  if (value !== value.trim()) throw new Error(`${path} must not have surrounding whitespace`);
  return value;
}
function integer(value, path, min = 0, max = 1000000) {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`${path} must be an integer in ${min}..${max}`);
  return value;
}
function boolean(value, path) {
  if (typeof value !== 'boolean') throw new Error(`${path} must be a boolean`);
  return value;
}
function choice(value, path, options) {
  if (!options.includes(value)) throw new Error(`${path} must be one of: ${options.join(', ')}`);
  return value;
}
function unique(values, path) {
  if (new Set(values).size !== values.length) throw new Error(`${path} contains duplicate identifiers`);
}
function compare(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
function minute(value, path, allowEnd = false) {
  if (allowEnd && value === '24:00') return 1440;
  if (typeof value !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) throw new Error(`${path} must be HH:MM${allowEnd ? ' (24:00 is allowed as an end)' : ''}`);
  return Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
}
function clock(value) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`; }
function interval(value, path) {
  object(value, path, ['start', 'end']);
  const start = minute(value.start, `${path}.start`), end = minute(value.end, `${path}.end`, true);
  if (start >= end) throw new Error(`${path}.end must be after start on the same day`);
  return { start, end };
}
function isoDate(value, path) {
  if (typeof value !== 'string' || !/^20\d\d-\d{2}-\d{2}$/.test(value)) throw new Error(`${path} must be a YYYY-MM-DD date in 2000..2099`);
  const date = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) throw new Error(`${path} is not a valid calendar date`);
  return date;
}

export const meta = {
  id: 'p11', title: 'Inventory Reorder Planner', category: 'Inventory', version:'1.1.0',
  description: 'Calculate reorder triggers, review-period targets, and pack-rounded purchase quantities.',
  fields: [{key:'reviewDays',label:'Review interval (days)',type:'number'},{key:'items',label:'Inventory items',type:'json'}],
  example: {reviewDays:7,items:[{sku:'FILTER',onHand:10,incoming:5,dailyUsage:5,leadDays:3,safetyStock:5,packSize:12,minimumOrder:24},{sku:'GLOVE',onHand:80,dailyUsage:4,leadDays:5}]}
};
export function run(input) {
  object(input, 'input', ['reviewDays', 'items']);
  const reviewDays = integer(input.reviewDays, 'reviewDays', 0, 365);
  const items = array(input.items, 'items', 1, 100).map((item, index) => {
    const p = `items[${index}]`;
    object(item, p, ['sku','onHand','incoming','dailyUsage','leadDays','safetyStock','packSize','minimumOrder']);
    const sku = string(item.sku, `${p}.sku`);
    const onHand = integer(item.onHand, `${p}.onHand`);
    const incoming = integer(item.incoming === undefined ? 0 : item.incoming, `${p}.incoming`);
    const dailyUsage = integer(item.dailyUsage, `${p}.dailyUsage`, 0, 10000);
    const leadDays = integer(item.leadDays, `${p}.leadDays`, 0, 365);
    const safety = integer(item.safetyStock === undefined ? 0 : item.safetyStock, `${p}.safetyStock`);
    const pack = integer(item.packSize === undefined ? 1 : item.packSize, `${p}.packSize`, 1, 100000);
    const minimum = integer(item.minimumOrder === undefined ? 0 : item.minimumOrder, `${p}.minimumOrder`);
    const stockPosition = onHand + incoming;
    const reorderPoint = dailyUsage * leadDays + safety;
    const targetStock = dailyUsage * (leadDays + reviewDays) + safety;
    const shortage = Math.max(0, targetStock - stockPosition);
    const orderQuantity = stockPosition <= reorderPoint && shortage > 0 ? Math.ceil(Math.max(shortage, minimum) / pack) * pack : 0;
    return {sku, stockPosition, reorderPoint, targetStock, orderQuantity, projectedStock:stockPosition + orderQuantity,
      daysOnHand:dailyUsage === 0 ? null : Number((onHand / dailyUsage).toFixed(2)), status:orderQuantity ? 'reorder' : 'sufficient'};
  });
  unique(items.map(item => item.sku), 'items.sku');
  return {items,totalOrderUnits:items.reduce((sum,item) => sum + item.orderQuantity,0),reorderCount:items.filter(item => item.orderQuantity > 0).length};
}
