get attachmentsDomain(){const domain=super.attachmentsDomain;domain.push(["mimetype","in",IMAGE_MIMETYPES]);if(!this.props.useMediaLibrary){domain.push("|",["url","=",false],"!","|",["url","=ilike","/html_editor/shape/%"],["url","=ilike","/web_editor/shape/%"]);}
domain.push("!",["name","=like","%.crop"]);domain.push("|",["type","=","binary"],"!",["url","=like","/%/static/%"]);if(!this.env.debug){const subDomain=[false];const originalId=this.props.media&&this.props.media.dataset.originalId;if(originalId){subDomain.push(originalId);}
domain.push(["original_id","in",subDomain]);}
return domain;}
