isInitialMedia(attachment){if(this.props.media.dataset.originalSrc){return this.props.media.dataset.originalSrc===attachment.image_src;}
return this.props.media.getAttribute("src")===attachment.image_src;}
async fetchAttachments(limit,offset){const attachments=await super.fetchAttachments(limit,offset);const primaryColors={};const htmlStyle=getHtmlStyle(document);for(let color=1;color<=5;color++){primaryColors[color]=getCSSVariableValue("o-color-"+color,htmlStyle);}
return attachments.map((attachment)=>{if(attachment.image_src.startsWith("/")){const newURL=new URL(attachment.image_src,window.location.origin);if(attachment.image_src.startsWith("/html_editor/shape/")||attachment.image_src.startsWith("/web_editor/shape/")){newURL.searchParams.forEach((value,key)=>{const match=key.match(/^c([1-5])$/);if(match){newURL.searchParams.set(key,primaryColors[match[1]]);}});}else{newURL.searchParams.set("height",2*this.MIN_ROW_HEIGHT);}
attachment.thumbnail_src=newURL.pathname+newURL.search;}
if(this.selectInitialMedia()&&this.isInitialMedia(attachment)){this.selectAttachment(attachment);}
return attachment;});}
