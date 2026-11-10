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
 id:'p17',title:'Procurement Quote Comparison',category:'Procurement',version:'1.1.0',
 description:'Compare delivered costs with order minimums, pack sizes, discounts, tax, and delivery eligibility.',
 fields:[{key:'quantity',label:'Required quantity',type:'number'},{key:'deadlineDays',label:'Delivery deadline (days)',type:'number'},{key:'quotes',label:'Supplier quotes',type:'json'}],
 example:{quantity:10,deadlineDays:7,quotes:[{supplier:'Atlas',unitPriceCents:100,shippingCents:100,taxBasisPoints:500,leadDays:3},{supplier:'Beacon',unitPriceCents:95,packSize:6,leadDays:5}]}
};
function basis(amount,points) {return Number((BigInt(amount)*BigInt(points)+5000n)/10000n);}
export function run(input) {
 object(input,'input',['quantity','deadlineDays','quotes']);
 const quantity=integer(input.quantity,'quantity',1,10000),deadline=integer(input.deadlineDays,'deadlineDays',0,365);
 const ranking=array(input.quotes,'quotes',1,100).map((q,i)=> {
  const p=`quotes[${i}]`;object(q,p,['supplier','unitPriceCents','shippingCents','taxBasisPoints','discountBasisPoints','minimumQuantity','packSize','leadDays']);
  const supplier=string(q.supplier,`${p}.supplier`),price=integer(q.unitPriceCents,`${p}.unitPriceCents`,0,10000000);
  const shippingCents=integer(q.shippingCents===undefined?0:q.shippingCents,`${p}.shippingCents`,0,1000000000);
  const taxRate=integer(q.taxBasisPoints===undefined?0:q.taxBasisPoints,`${p}.taxBasisPoints`,0,10000);
  const discountRate=integer(q.discountBasisPoints===undefined?0:q.discountBasisPoints,`${p}.discountBasisPoints`,0,10000);
  const minimum=integer(q.minimumQuantity===undefined?1:q.minimumQuantity,`${p}.minimumQuantity`,1,10000);
  const pack=integer(q.packSize===undefined?1:q.packSize,`${p}.packSize`,1,10000);
  const leadDays=integer(q.leadDays,`${p}.leadDays`,0,365);
  const orderQuantity=Math.ceil(Math.max(quantity,minimum)/pack)*pack;
  const subtotalCents=price*orderQuantity,discountCents=basis(subtotalCents,discountRate);
  const taxCents=basis(subtotalCents-discountCents+shippingCents,taxRate);
  const totalCents=subtotalCents-discountCents+shippingCents+taxCents;
  return {supplier,orderQuantity,excessQuantity:orderQuantity-quantity,subtotalCents,discountCents,shippingCents,taxCents,totalCents,effectiveUnitCostCents:Math.round(totalCents/quantity),leadDays,eligible:leadDays<=deadline};
 });
 unique(ranking.map(q=>q.supplier),'quotes.supplier');
 ranking.sort((a,b)=>Number(b.eligible)-Number(a.eligible)||a.totalCents-b.totalCents||a.leadDays-b.leadDays||compare(a.supplier,b.supplier));
 return {quantity,ranking,recommendedSupplier:ranking.find(q=>q.eligible)?.supplier ?? null};
}
