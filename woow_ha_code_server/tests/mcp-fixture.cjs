// Isolated live-test server. The random proof is only available through tools/call.
const fs=require('node:fs'), readline=require('node:readline');
readline.createInterface({input:process.stdin}).on('line',line=>{
 let q;try{q=JSON.parse(line);}catch{return;}
 if(q.id===undefined)return;
 let result;
 if(q.method==='initialize')result={protocolVersion:'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'woow-agent-live-test',version:'1.0.0'}};
 else if(q.method==='tools/list')result={tools:[{name:'read_proof',description:'Return the private deployment test proof. Call this tool to verify the shared MCP configuration.',inputSchema:{type:'object',properties:{},additionalProperties:false}}]};
 else if(q.method==='tools/call'&&q.params?.name==='read_proof') {
  fs.appendFileSync(process.env.WOOW_PROOF_LOG,JSON.stringify({at:new Date().toISOString(),method:q.method,tool:q.params.name})+'\n');
  result={content:[{type:'text',text:fs.readFileSync(process.env.WOOW_PROOF_FILE,'utf8').trim()}]};
 } else if(q.method==='ping')result={};
 else {process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:q.id,error:{code:-32601,message:'Method not found'}})+'\n');return;}
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:q.id,result})+'\n');
});
