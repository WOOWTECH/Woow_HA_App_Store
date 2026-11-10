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
 id:'p19',title:'Staff Coverage Matrix',category:'Workforce',version: '1.1.0',
 description:'Compare role demand with staffed intervals and quantify gaps in staff-minutes.',
 fields:[{key:'requirements',label:'Role coverage requirements',type:'json'},{key:'shifts',label:'Staff shifts',type:'json'}],
 example:{requirements:[{role:'Support',start:'09:00',end:'11:00',minimumStaff:2}],shifts:[{staff:'Ada',role:'Support',start:'09:00',end:'11:00'},{staff:'Ben',role:'Support',start:'10:00',end:'11:00'}]}
};
export function run(input) {
 object(input,'input',['requirements','shifts']);
 const requirements=array(input.requirements,'requirements',1,100).map((r,i)=> {
  const p=`requirements[${i}]`;object(r,p,['role','start','end','minimumStaff']);
  return {role:string(r.role,`${p}.role`),...interval({start:r.start,end:r.end},p),minimumStaff:integer(r.minimumStaff,`${p}.minimumStaff`,1,100)};
 });
 const shifts=array(input.shifts,'shifts',0,200).map((s,i)=> {
  const p=`shifts[${i}]`;object(s,p,['staff','role','start','end']);
  return {staff:string(s.staff,`${p}.staff`),role:string(s.role,`${p}.role`),...interval({start:s.start,end:s.end},p)};
 });
 const staffShifts=shifts.slice().sort((a,b)=>compare(a.staff,b.staff)||a.start-b.start||a.end-b.end);
 for(let i=1;i<staffShifts.length;i++) {
  const a=staffShifts[i-1],b=staffShifts[i];
  if(a.staff===b.staff && b.start<a.end) throw new Error(`Staff ${a.staff} has overlapping shifts; a person cannot cover two shifts at once`);
 }
 const coverage=[];let totalRequiredStaffMinutes=0,totalUncoveredStaffMinutes=0;
 const roles=[...new Set(requirements.map(r=>r.role))].sort(compare);
 for(const role of roles) {
  const demands=requirements.filter(r=>r.role===role),assigned=shifts.filter(s=>s.role===role);
  const boundaries=[...new Set([...demands,...assigned].flatMap(w=>[w.start,w.end]))].sort((a,b)=>a-b);
  for(let i=0;i<boundaries.length-1;i++) {
   const start=boundaries[i],end=boundaries[i+1];
   const requiredStaff=demands.filter(r=>r.start<=start && r.end>=end).reduce((sum,r)=>sum+r.minimumStaff,0);
   if(requiredStaff===0)continue;
   const assignedStaff=assigned.filter(s=>s.start<=start && s.end>=end).map(s=>s.staff).sort(compare);
   const availableStaff=assignedStaff.length,shortfall=Math.max(0,requiredStaff-availableStaff),surplus=Math.max(0,availableStaff-requiredStaff);
   coverage.push({role,start:clock(start),end:clock(end),requiredStaff,assignedStaff,availableStaff,shortfall,surplus});
   totalRequiredStaffMinutes+=(end-start)*requiredStaff;totalUncoveredStaffMinutes+=(end-start)*shortfall;
  }
 }
 return {coverage,covered:totalUncoveredStaffMinutes===0,totalRequiredStaffMinutes,totalUncoveredStaffMinutes};
}
