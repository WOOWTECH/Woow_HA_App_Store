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
 id:'p14',title:'Expense Splitting Ledger',category:'Finance',version:'1.1.0',
 description:'Split integer-cent expenses by weights and reconcile exact member balances into suggested transfers.',
 fields:[{key:'members',label:'Members',type:'json'},{key:'expenses',label:'Expenses (integer cents)',type:'json'}],
 example:{members:['Ada','Ben','Chen'],expenses:[{id:'Dinner',paidBy:'Ada',amountCents:3000},{id:'Taxi',paidBy:'Ben',amountCents:1500,split:[{member:'Ada',weight:1},{member:'Ben',weight:1}]}]}
};
export function run(input) {
 object(input,'input',['members','expenses']);
 const members=array(input.members,'members',1,50).map((m,i)=>string(m,`members[${i}]`));
 unique(members,'members');
 const memberIndex=new Map(members.map((m,i)=>[m,i]));
 const balances=members.map(member=>({member,paidCents:0,owedCents:0,balanceCents:0}));
 const expenses=array(input.expenses,'expenses',0,200).map((expense,i)=> {
  const p=`expenses[${i}]`;object(expense,p,['id','paidBy','amountCents','split']);
  const id=string(expense.id,`${p}.id`),paidBy=string(expense.paidBy,`${p}.paidBy`);
  if(!memberIndex.has(paidBy)) throw new Error(`${p}.paidBy is an unknown member`);
  const amountCents=integer(expense.amountCents,`${p}.amountCents`,1,1000000000);
  const split=expense.split===undefined?members.map(member=>({member,weight:1})):array(expense.split,`${p}.split`,1,50).map((s,j)=> {
   object(s,`${p}.split[${j}]`,['member','weight']);
   const member=string(s.member,`${p}.split[${j}].member`);
   if(!memberIndex.has(member)) throw new Error(`${p}.split[${j}] has an unknown member`);
   return {member,weight:integer(s.weight,`${p}.split[${j}].weight`,1,10000)};
  });
  unique(split.map(s=>s.member),`${p}.split.member`);
  const weightTotal=split.reduce((sum,s)=>sum+s.weight,0);
  const apportioned=split.map(s=>({member:s.member,amountCents:Math.floor(amountCents*s.weight/weightTotal),remainder:(amountCents*s.weight)%weightTotal}));
  let leftover=amountCents-apportioned.reduce((sum,s)=>sum+s.amountCents,0);
  apportioned.sort((a,b)=>b.remainder-a.remainder || memberIndex.get(a.member)-memberIndex.get(b.member));
  for(let j=0;j<leftover;j++) apportioned[j].amountCents++;
  apportioned.sort((a,b)=>memberIndex.get(a.member)-memberIndex.get(b.member));
  const shares=apportioned.map(({member,amountCents})=>({member,amountCents}));
  balances[memberIndex.get(paidBy)].paidCents+=amountCents;
  for(const s of shares) balances[memberIndex.get(s.member)].owedCents+=s.amountCents;
  return {id,paidBy,amountCents,shares};
 });
 unique(expenses.map(e=>e.id),'expenses.id');
 for(const b of balances) b.balanceCents=b.paidCents-b.owedCents;
 const debtors=balances.filter(b=>b.balanceCents<0).map(b=>({member:b.member,remaining:-b.balanceCents}));
 const creditors=balances.filter(b=>b.balanceCents>0).map(b=>({member:b.member,remaining:b.balanceCents}));
 const settlements=[];let d=0,c=0;
 while(d<debtors.length && c<creditors.length) {
  const amountCents=Math.min(debtors[d].remaining,creditors[c].remaining);
  settlements.push({from:debtors[d].member,to:creditors[c].member,amountCents});
  debtors[d].remaining-=amountCents;creditors[c].remaining-=amountCents;
  if(debtors[d].remaining===0)d++;if(creditors[c].remaining===0)c++;
 }
 return {expenses,balances,settlements,totalCents:expenses.reduce((sum,e)=>sum+e.amountCents,0)};
}
