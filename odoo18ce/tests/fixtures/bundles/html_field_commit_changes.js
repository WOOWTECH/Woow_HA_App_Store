async _commitChanges({urgent}){if(status(this)==="destroyed"){return;}
if(this.isDirty){if(this.state.showCodeView){await this.updateValue(this.codeViewRef.el.value);return;}
if(urgent){await this.updateValue(this.editor.getContent());}
const changeId=this.lastChangeId;const el=await this.getEditorContent();const content=el.innerHTML;this.clearElementToCompare(el);const comparisonValue=el.innerHTML;if(!urgent||(urgent&&this.lastValue!==comparisonValue)){await this.updateValue(content,{changeId});}}}
