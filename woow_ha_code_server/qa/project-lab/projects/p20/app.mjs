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
 id:'p20',title:'Milestone Dependency Scheduling',category:'Project Planning',version: '1.1.0',
 description:'Schedule a dependency graph on business days and calculate critical milestones and total slack.',
 fields:[{key:'startDate',label:'Earliest project start (YYYY-MM-DD)',type:'text'},{key:'holidays',label:'Excluded holiday dates',type:'json'},{key:'milestones',label:'Milestones and dependencies',type:'json'}],
 example:{startDate:'2026-11-09',holidays:[],milestones:[{id:'Design',durationDays:2},{id:'Build',durationDays:3,dependsOn:['Design']},{id:'Docs',durationDays:1,dependsOn:['Design']},{id:'Launch',durationDays:1,dependsOn:['Build','Docs']}]}
};
export function run(input) {
 object(input,'input',['startDate','holidays','milestones']);
 const requestedStart=isoDate(input.startDate,'startDate');
 const holidays=array(input.holidays===undefined?[]:input.holidays,'holidays',0,366).map((h,i)=> {isoDate(h,`holidays[${i}]`);return h;});
 unique(holidays,'holidays');const holidaySet=new Set(holidays);
 const milestones=array(input.milestones,'milestones',1,100).map((m,i)=> {
  const p=`milestones[${i}]`;object(m,p,['id','durationDays','dependsOn']);
  const id=string(m.id,`${p}.id`),durationDays=integer(m.durationDays,`${p}.durationDays`,1,365);
  const dependsOn=array(m.dependsOn===undefined?[]:m.dependsOn,`${p}.dependsOn`,0,99).map((d,j)=>string(d,`${p}.dependsOn[${j}]`));
  unique(dependsOn,`${p}.dependsOn`);
  return {id,durationDays,dependsOn,position:i,start:0,finish:0,latestStart:0,successors:[],indegree:dependsOn.length};
 });
 unique(milestones.map(m=>m.id),'milestones.id');
 const byId=new Map(milestones.map(m=>[m.id,m]));
 for(const m of milestones) for(const dep of m.dependsOn) {
  if(!byId.has(dep)) throw new Error(`Milestone ${m.id} has unknown dependency ${dep}`);
  byId.get(dep).successors.push(m.id);
 }
 const ready=milestones.filter(m=>m.indegree===0),ordered=[];
 while(ready.length) {
  ready.sort((a,b)=>a.position-b.position);
  const m=ready.shift();
  m.start=Math.max(0,...m.dependsOn.map(id=>byId.get(id).finish));m.finish=m.start+m.durationDays;
  ordered.push(m);
  for(const id of m.successors) {const next=byId.get(id);next.indegree--;if(next.indegree===0)ready.push(next);}
 }
 if(ordered.length!==milestones.length) throw new Error('Milestone dependencies contain a cycle');
 const projectDurationDays=Math.max(...ordered.map(m=>m.finish));
 for(const m of ordered.slice().reverse()) {
  const latestFinish=m.successors.length?Math.min(...m.successors.map(id=>byId.get(id).latestStart)):projectDurationDays;
  m.latestStart=latestFinish-m.durationDays;
 }
 const dates=[],day=new Date(requestedStart);
 while(dates.length<projectDurationDays) {
  const date=day.toISOString().slice(0,10),weekday=day.getUTCDay();
  if(weekday!==0 && weekday!==6 && !holidaySet.has(date)) dates.push(date);
  day.setUTCDate(day.getUTCDate()+1);
 }
 const schedule=ordered.map(m=>({id:m.id,durationDays:m.durationDays,startOffset:m.start,finishOffset:m.finish,startDate:dates[m.start],finishDate:dates[m.finish-1],slackDays:m.latestStart-m.start,critical:m.latestStart===m.start}));
 return {schedule,projectDurationDays,projectStartDate:dates[0],projectFinishDate:dates.at(-1),criticalMilestones:schedule.filter(m=>m.critical).map(m=>m.id),topologicalOrder:ordered.map(m=>m.id)};
}
