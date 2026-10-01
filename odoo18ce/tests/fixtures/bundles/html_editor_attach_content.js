attachTo(editable){if(this.isDestroyed||this.editable){throw new Error("Cannot re-attach an editor");}
this.editable=editable;this.document=editable.ownerDocument;if(this.config.content){editable.innerHTML=fixInvalidHTML(this.config.content);if(isEmpty(editable)){const baseContainer=createBaseContainer(this.config.baseContainer,this.document);fillShrunkPhrasingParent(baseContainer);editable.replaceChildren(baseContainer);}}
this.preparePlugins();editable.setAttribute("contenteditable",true);editable.setAttribute("translate","no");initElementForEdition(editable,{allowInlineAtRoot:!!this.config.allowInlineAtRoot});editable.classList.add("odoo-editor-editable");if(this.config.classList){editable.classList.add(...this.config.classList);}
if(this.config.height){editable.style.height=this.config.height;}
this.startPlugins();this.config.onEditorReady?.();}
