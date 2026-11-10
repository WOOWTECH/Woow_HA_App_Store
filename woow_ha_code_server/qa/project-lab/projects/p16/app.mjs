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

function timestamp(value,path) {
 if(typeof value!=='string' || !/^20\d\d-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\dZ$/.test(value)) throw new Error(`${path} must be YYYY-MM-DDTHH:MMZ in UTC (2000..2099)`);
 const ms=Date.parse(value);
 if(!Number.isFinite(ms) || new Date(ms).toISOString().slice(0,16)+'Z'!==value) throw new Error(`${path} is not a valid calendar timestamp`);
 return ms/60000;
}
function stamp(value) {return new Date(value*60000).toISOString().slice(0,16)+'Z';}
export const meta = {
 id:'p16',title:'Reservation Collision Detector',category:'Reservations',version:'1.1.0',
 description:'Detect shared-resource booking overlaps and post-booking turnaround conflicts in UTC.',
 fields:[{key:'turnaroundMinutes',label:'Turnaround after each booking (minutes)',type:'number'},{key:'reservations',label:'Reservations',type:'json'}],
 example:{turnaroundMinutes:15,reservations:[{id:'R1',resource:'Room A',start:'2026-11-10T09:00Z',end:'2026-11-10T10:00Z'},{id:'R2',resource:'Room A',start:'2026-11-10T10:00Z',end:'2026-11-10T11:00Z'}]}
};
export function run(input) {
 object(input,'input',['turnaroundMinutes','reservations']);
 const gap=integer(input.turnaroundMinutes===undefined?0:input.turnaroundMinutes,'turnaroundMinutes',0,1440);
 const reservations=array(input.reservations,'reservations',0,200).map((r,i)=> {
  const p=`reservations[${i}]`;object(r,p,['id','resource','start','end']);
  const id=string(r.id,`${p}.id`),resource=string(r.resource,`${p}.resource`),start=timestamp(r.start,`${p}.start`),end=timestamp(r.end,`${p}.end`);
  if(end<=start || end-start>10080) throw new Error(`${p}.end must be after start, with duration no greater than 7 days`);
  return {id,resource,start,end};
 });
 unique(reservations.map(r=>r.id),'reservations.id');
 reservations.sort((a,b)=>compare(a.resource,b.resource)||a.start-b.start||compare(a.id,b.id));
 const conflicts=[];
 for(let i=0;i<reservations.length;i++) for(let j=i+1;j<reservations.length;j++) {
  const a=reservations[i],b=reservations[j];
  if(a.resource!==b.resource) break;
  if(b.start>=a.end+gap) break;
  const start=Math.max(a.start,b.start),end=Math.min(a.end+gap,b.end+gap);
  if(start<end) conflicts.push({resource:a.resource,firstId:a.id,secondId:b.id,kind:Math.max(a.start,b.start)<Math.min(a.end,b.end)?'overlap':'turnaround',conflictStart:stamp(start),conflictEnd:stamp(end),conflictMinutes:end-start});
 }
 return {valid:conflicts.length===0,conflicts,resourceCount:new Set(reservations.map(r=>r.resource)).size,reservationCount:reservations.length};
}
