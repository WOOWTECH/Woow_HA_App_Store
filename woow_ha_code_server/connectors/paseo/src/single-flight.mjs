import {performance} from 'node:perf_hooks';
const pending=new Map();
/** Coalesce overlapping reads; never retain a completed or failed snapshot. */
export function singleFlight(key,read) {
 if(pending.has(key))return pending.get(key);
 const task=Promise.resolve().then(read);
 pending.set(key,task);
 const release=()=>{if(pending.get(key)===task)pending.delete(key);};
 task.then(release,release);
 return task;
}

/** Bound provider probe frequency; failed probes are never cached. */
export function createReadWindow({ttlMs=3000,maxEntries=32,now=()=>performance.now(),wallNow=Date.now}={}) {
 const values=new Map(),active=new Map();
 return function readWindow(key,read) {
  const cached=values.get(key);
  if(cached&&now()-cached.readAt<ttlMs)return Promise.resolve(cached.result);
  if(active.has(key))return active.get(key);
  const task=Promise.resolve().then(read).then(value=>{
   const result={value,checkedAt:wallNow()};
   values.delete(key);values.set(key,{result,readAt:now()});
   while(values.size>maxEntries)values.delete(values.keys().next().value);
   return result;
  });
  active.set(key,task);
  const release=()=>{if(active.get(key)===task)active.delete(key);};
  task.then(release,release);
  return task;
 };
}
export const daemonStatusWindow=createReadWindow();
