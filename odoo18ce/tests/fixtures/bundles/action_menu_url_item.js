async onItemSelected(item){if(!(await this.props.shouldExecuteAction(item))){return;}
if(item.callback){item.callback([item]);}else if(item.action){this.executeAction(item.action);}else if(item.url){browser.location=item.url;}}
