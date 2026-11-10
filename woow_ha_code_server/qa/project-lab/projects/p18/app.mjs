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
 id:'p18',title:'Fulfillment Allocation',category:'Fulfillment',version: '1.1.0',
 description:'Allocate scarce stock by order priority with atomic whole-order or partial-fulfillment policies.',
 fields:[{key:'stock',label:'Available stock',type:'json'},{key:'orders',label:'Orders',type:'json'}],
 example:{stock:[{sku:'A',quantity:5},{sku:'B',quantity:2}],orders:[{id:'Standard',priority:2,lines:[{sku:'A',quantity:4}]},{id:'Urgent',priority:1,lines:[{sku:'A',quantity:3},{sku:'B',quantity:2}]}]}
};
export function run(input) {
 object(input,'input',['stock','orders']);
 const stock=array(input.stock,'stock',1,100).map((s,i)=> {
  object(s,`stock[${i}]`,['sku','quantity']);
  return {sku:string(s.sku,`stock[${i}].sku`),quantity:integer(s.quantity,`stock[${i}].quantity`)};
 });
 unique(stock.map(s=>s.sku),'stock.sku');
 const available=new Map(stock.map(s=>[s.sku,s.quantity]));
 const pending=array(input.orders,'orders',0,100).map((o,i)=> {
  const p=`orders[${i}]`;object(o,p,['id','priority','allowPartial','lines']);
  const id=string(o.id,`${p}.id`),priority=integer(o.priority,`${p}.priority`,1,5);
  const allowPartial=boolean(o.allowPartial===undefined?false:o.allowPartial,`${p}.allowPartial`);
  const lines=array(o.lines,`${p}.lines`,1,50).map((l,j)=> {
   object(l,`${p}.lines[${j}]`,['sku','quantity']);
   const sku=string(l.sku,`${p}.lines[${j}].sku`),quantity=integer(l.quantity,`${p}.lines[${j}].quantity`,1,1000000);
   if(!available.has(sku)) throw new Error(`${p}.lines[${j}] has an unknown SKU ${sku}`);
   return {sku,quantity};
  });
  unique(lines.map(l=>l.sku),`${p}.lines.sku`);
  return {id,priority,allowPartial,lines,position:i};
 });
 unique(pending.map(o=>o.id),'orders.id');
 pending.sort((a,b)=>a.priority-b.priority||a.position-b.position);
 const totals={requestedUnits:0,allocatedUnits:0,backorderedUnits:0,fulfilledOrders:0};
 const orders=pending.map(o=> {
  const skip=!o.allowPartial && o.lines.some(l=>available.get(l.sku)<l.quantity);
  const allocated=[],backordered=[];
  for(const l of o.lines) {
   const qty=skip?0:Math.min(l.quantity,available.get(l.sku)),missing=l.quantity-qty;
   available.set(l.sku,available.get(l.sku)-qty);
   if(qty)allocated.push({sku:l.sku,quantity:qty});
   if(missing)backordered.push({sku:l.sku,quantity:missing});
   totals.requestedUnits+=l.quantity;totals.allocatedUnits+=qty;totals.backorderedUnits+=missing;
  }
  const status=backordered.length===0?'fulfilled':allocated.length===0?'backordered':'partial';
  if(status==='fulfilled')totals.fulfilledOrders++;
  return {id:o.id,priority:o.priority,status,allocated,backordered};
 });
 return {orders,remainingStock:stock.map(s=>({sku:s.sku,quantity:available.get(s.sku)})),totals};
}
