resetContent(value){value=value||'<p><br></p>';this.editable.innerHTML=value;this.sanitize(this.editable);this.historyStep(true);this._toRollback=false;if(this.editable.textContent===''&&this.options.placeholder){this._makeHint(this.editable.firstChild,this.options.placeholder,true);}
this.multiselectionRefresh();}
