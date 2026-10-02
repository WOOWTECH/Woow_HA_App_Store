async fetchAttachments(...args){const attachments=await super.fetchAttachments(...args);if(this.selectInitialMedia()){for(const attachment of attachments){if(`/web/content/${attachment.id}`===this.props.media.getAttribute('href').replace(/[?].*/,'')){this.selectAttachment(attachment);}}}
return attachments;}
