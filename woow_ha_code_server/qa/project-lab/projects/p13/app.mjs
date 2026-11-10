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
 id:'p13',title:'Meeting Slot Overlap Finder',category:'Scheduling',version:'1.1.0',
 description:'Intersect everyone’s availability and find duration-fitting meeting starts on a shared time grid.',
 fields:[{key:'durationMinutes',label:'Meeting duration (minutes)',type:'number'},{key:'stepMinutes',label:'Start grid (minutes)',type:'number'},{key:'participants',label:'Participant availability',type:'json'}],
 example:{durationMinutes:30,stepMinutes:30,participants:[{name:'Ada',availability:[{start:'09:00',end:'12:00'}]},{name:'Ben',availability:[{start:'10:00',end:'11:00'}]}]}
};
function merge(windows) {
 const sorted = windows.slice().sort((a,b)=>a.start-b.start || a.end-b.end), result=[];
 for(const w of sorted) {
  const tail=result.at(-1);
  if(tail && w.start<=tail.end) tail.end=Math.max(tail.end,w.end);
  else result.push({...w});
 }
 return result;
}
export function run(input) {
 object(input,'input',['durationMinutes','stepMinutes','participants']);
 const duration = integer(input.durationMinutes,'durationMinutes',1,480);
 const step = integer(input.stepMinutes===undefined?15:input.stepMinutes,'stepMinutes',1,180);
 const participants = array(input.participants,'participants',1,30).map((p,i)=> {
  object(p,`participants[${i}]`,['name','availability']);
  return {name:string(p.name,`participants[${i}].name`),windows:merge(array(p.availability,`participants[${i}].availability`,0,50).map((w,j)=>interval(w,`participants[${i}].availability[${j}]`)))};
 });
 unique(participants.map(p=>p.name),'participants.name');
 let common=participants[0].windows;
 for(const p of participants.slice(1)) {
  const intersection=[]; let a=0,b=0;
  while(a<common.length && b<p.windows.length) {
   const left=common[a],right=p.windows[b],start=Math.max(left.start,right.start),end=Math.min(left.end,right.end);
   if(start<end) intersection.push({start,end});
   if(left.end<right.end) a++; else b++;
  }
  common=intersection;
 }
 const slots=[];
 for(const w of common) for(let start=Math.ceil(w.start/step)*step;start+duration<=w.end;start+=step) slots.push({start:clock(start),end:clock(start+duration)});
 return {commonWindows:common.map(w=>({start:clock(w.start),end:clock(w.end),durationMinutes:w.end-w.start})),slots,slotCount:slots.length};
}
