hasSeenFeature=Record.attr(false,{compute(){return this.store.channel_types_with_seen_infos.includes(this.channel_type);},});get invitationLink(){if(!this.uuid||this.channel_type==="chat"){return undefined;}
return`${window.location.origin}/chat/${this.id}/${this.uuid}`;}
get isEmpty(){return!this.messages.some((message)=>!message.isEmpty);}
