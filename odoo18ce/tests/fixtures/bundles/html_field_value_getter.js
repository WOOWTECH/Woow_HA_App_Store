get value(){const value=this.props.record.data[this.props.name];const newVal=this.htmlUpgradeManager.processForUpgrade(fixInvalidHTML(value),{containsComplexHTML:this.state.containsComplexHTML,env:this.env,});if(instanceofMarkup(value)){return markup(newVal);}
return newVal;}
