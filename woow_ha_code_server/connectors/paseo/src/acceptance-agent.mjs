/** Archive only an agent created by this call, retaining its verification history. */
export async function usingAcceptanceAgent(client,options,row,verify) {
 const agent=await client.createAgent(options);
 if(!agent?.id)throw new Error('Agent creation was not confirmed');
 row.agentId=agent.id;
 try {return await verify(agent);}
 finally {
  try {
   const receipt=await client.archiveAgent(agent.id);
   if(receipt?.archivedAt===undefined||receipt.archivedAt===null)throw new Error('Unconfirmed cleanup');
   row.cleanup={archived:true};
  } catch {row.cleanup={archived:false,code:'ACCEPTANCE_CLEANUP_FAILED'};}
 }
}
