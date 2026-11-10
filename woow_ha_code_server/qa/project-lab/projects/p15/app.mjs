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
 id:'p15',title:'Service Ticket Priority Triage',category:'Service Operations',version:'1.1.0',
 description:'Explain ticket priority scores, apply response-time targets, and order the support queue.',
 fields:[{key:'tickets',label:'Service tickets',type:'json'}],
 example:{tickets:[{id:'T-101',impact:'one',urgency:'low',ageHours:0},{id:'T-102',impact:'many',urgency:'high',ageHours:5},{id:'T-103',impact:'all',urgency:'high',ageHours:0}]}
};
export function run(input) {
 object(input,'input',['tickets']);
 const queue=array(input.tickets,'tickets',0,200).map((t,i)=> {
  const p=`tickets[${i}]`;
  object(t,p,['id','impact','urgency','ageHours','outage','securityIncident']);
  const id=string(t.id,`${p}.id`),impact=choice(t.impact,`${p}.impact`,['one','many','all']),urgency=choice(t.urgency,`${p}.urgency`,['low','normal','high']);
  const age=integer(t.ageHours,`${p}.ageHours`,0,87600);
  const outage=boolean(t.outage===undefined?false:t.outage,`${p}.outage`);
  const security=boolean(t.securityIncident===undefined?false:t.securityIncident,`${p}.securityIncident`);
  const score={one:10,many:30,all:50}[impact]+{low:0,normal:15,high:30}[urgency]+(outage?20:0)+(security?40:0);
  const priority=score>=80?'P1':score>=50?'P2':score>=25?'P3':'P4';
  const slaHours={P1:1,P2:4,P3:24,P4:72}[priority];
  const reasons=[`impact:${impact}`,`urgency:${urgency}`];
  if(outage)reasons.push('outage');if(security)reasons.push('security_incident');
  return {id,score,priority,slaHours,elapsedHours:age,remainingHours:slaHours-age,slaState:age>slaHours?'breached':age===slaHours?'due':'within_sla',reasons};
 });
 unique(queue.map(t=>t.id),'tickets.id');
 queue.sort((a,b)=>compare(a.priority,b.priority)||a.remainingHours-b.remainingHours||b.score-a.score||compare(a.id,b.id));
 return {queue,counts:Object.fromEntries(['P1','P2','P3','P4'].map(p=>[p,queue.filter(t=>t.priority===p).length])),breachedCount:queue.filter(t=>t.slaState==='breached').length,dueCount:queue.filter(t=>t.slaState==='due').length};
}
