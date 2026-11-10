import path from 'node:path';
import {RuntimeError} from './state.mjs';

// Reuse the dedicated check directory so repeated acceptance does not leave one
// new workspace per provider. Never archive or modify an existing workspace.
export async function acceptanceWorkspace(client,cwd){
 const directory=path.resolve(cwd),seen=new Set();let cursor;
 for(let page=0;page<100;page++){
  const result=await client.fetchWorkspaces({page:{limit:200,...(cursor?{cursor}:{})}});
  if(!Array.isArray(result?.entries))throw new RuntimeError('WORKSPACE_LIST_FAILED');
  const match=result.entries.find(w=>typeof w.id==='string'&&typeof w.workspaceDirectory==='string'&&path.resolve(w.workspaceDirectory)===directory&&!w.archivingAt);
  if(match)return match.id;
  if(!result.pageInfo?.hasMore){
   const created=await client.createWorkspace({source:{kind:'directory',path:directory}});
   if(!created.workspace?.id)throw new RuntimeError('WORKSPACE_CREATE_FAILED');
   return created.workspace.id;
  }
  cursor=result.pageInfo.nextCursor;
  if(typeof cursor!=='string'||!cursor||seen.has(cursor))throw new RuntimeError('WORKSPACE_LIST_FAILED');
  seen.add(cursor);
 }
 throw new RuntimeError('WORKSPACE_LIST_FAILED');
}
