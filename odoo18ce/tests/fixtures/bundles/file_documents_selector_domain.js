get attachmentsDomain(){const domain=super.attachmentsDomain.map((d)=>{if(d[0]==="mimetype"){return["mimetype","!=",false];}
return d;});domain.unshift("&","|",["url","=",null],"&","!",["url","=like","/%/static/%"],"!","|",["url","=ilike","/html_editor/shape/%"],["url","=ilike","/web_editor/shape/%"]);domain.push("!",["name","=like","%.crop"]);return domain;}
