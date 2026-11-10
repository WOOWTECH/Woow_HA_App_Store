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

const states = ['backlog','ready','in_progress','review','done','blocked'];
const moves = {backlog:['ready'],ready:['in_progress','backlog'],in_progress:['review','blocked'],review:['done','in_progress'],done:['ready'],blocked:['in_progress','backlog']};
export const meta = {
  id:'p12',title:'Kanban Transition Validator',category:'Workflow',version:'1.1.0',
  description:'Apply atomic task transitions while enforcing workflow edges and completed prerequisites.',
  fields:[{key:'tasks',label:'Tasks',type:'json'},{key:'transitions',label:'Requested transitions',type:'json'}],
  example:{tasks:[{id:'DESIGN',status:'done'},{id:'BUILD',status:'ready',dependencies:['DESIGN']}],transitions:[{id:'BUILD',to:'in_progress'},{id:'BUILD',to:'review'},{id:'BUILD',to:'done'}]}
};
export function run(input) {
  object(input,'input',['tasks','transitions']);
  const tasks = array(input.tasks,'tasks',1,100).map((t,i) => {
    object(t,`tasks[${i}]`,['id','status','dependencies']);
    const dependencies = array(t.dependencies === undefined ? [] : t.dependencies,`tasks[${i}].dependencies`,0,99).map((id,j) => string(id,`tasks[${i}].dependencies[${j}]`));
    unique(dependencies,`tasks[${i}].dependencies`);
    return {id:string(t.id,`tasks[${i}].id`),status:choice(t.status,`tasks[${i}].status`,states),dependencies};
  });
  unique(tasks.map(t=>t.id),'tasks.id');
  const byId = new Map(tasks.map(t=>[t.id,t]));
  for (const t of tasks) for (const id of t.dependencies) if (!byId.has(id)) throw new Error(`Task ${t.id}: unknown dependency ${id}`);
  const visiting = new Set(), visited = new Set();
  function visit(t) {
    if (visiting.has(t.id)) throw new Error(`Dependency cycle involving ${t.id}`);
    if (visited.has(t.id)) return;
    visiting.add(t.id);
    for (const dep of t.dependencies) visit(byId.get(dep));
    visiting.delete(t.id); visited.add(t.id);
  }
  tasks.forEach(visit);
  function checkDependencies(context) {
    for (const t of tasks) if (['in_progress','review','done'].includes(t.status)) {
      for (const id of t.dependencies) if (byId.get(id).status !== 'done') throw new Error(`${context}: task ${t.id} requires completed dependency ${id}`);
    }
  }
  checkDependencies('Initial board');
  const history = [];
  array(input.transitions,'transitions',0,200).forEach((change,i)=> {
    object(change,`transitions[${i}]`,['id','to']);
    const id = string(change.id,`transitions[${i}].id`), to = choice(change.to,`transitions[${i}].to`,states);
    const t = byId.get(id);
    if (!t) throw new Error(`transitions[${i}]: unknown task ${id}`);
    if (!moves[t.status].includes(to)) throw new Error(`transitions[${i}]: transition ${t.status} -> ${to} is not allowed`);
    const from = t.status;
    t.status = to;
    checkDependencies(`transitions[${i}]`);
    history.push({id,from,to});
  });
  return {tasks,history,counts:Object.fromEntries(states.map(state=>[state,tasks.filter(t=>t.status===state).length]))};
}
