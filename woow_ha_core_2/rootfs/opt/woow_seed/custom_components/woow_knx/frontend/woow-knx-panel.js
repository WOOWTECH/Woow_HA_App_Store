/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t=globalThis,e=t.ShadowRoot&&(void 0===t.ShadyCSS||t.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),s=new WeakMap;let r=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const i=this.t;if(e&&void 0===t){const e=void 0!==i&&1===i.length;e&&(t=s.get(i)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&s.set(i,t))}return t}toString(){return this.cssText}};const o=e?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const i of t.cssRules)e+=i.cssText;return(t=>new r("string"==typeof t?t:t+"",void 0,i))(e)})(t):t,{is:n,defineProperty:a,getOwnPropertyDescriptor:l,getOwnPropertyNames:c,getOwnPropertySymbols:d,getPrototypeOf:h}=Object,p=globalThis,_=p.trustedTypes,u=_?_.emptyScript:"",f=p.reactiveElementPolyfillSupport,g=(t,e)=>t,v={toAttribute(t,e){switch(e){case Boolean:t=t?u:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let i=t;switch(e){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t)}catch(t){i=null}}return i}},b=(t,e)=>!n(t,e),y={attribute:!0,type:String,converter:v,reflect:!1,useDefault:!1,hasChanged:b};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */Symbol.metadata??=Symbol("metadata"),p.litPropertyMetadata??=new WeakMap;let m=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=y){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const i=Symbol(),s=this.getPropertyDescriptor(t,i,e);void 0!==s&&a(this.prototype,t,s)}}static getPropertyDescriptor(t,e,i){const{get:s,set:r}=l(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:s,set(e){const o=s?.call(this);r?.call(this,e),this.requestUpdate(t,o,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??y}static _$Ei(){if(this.hasOwnProperty(g("elementProperties")))return;const t=h(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(g("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(g("properties"))){const t=this.properties,e=[...c(t),...d(t)];for(const i of e)this.createProperty(i,t[i])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const i=this._$Eu(t,e);void 0!==i&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const i=new Set(t.flat(1/0).reverse());for(const t of i)e.unshift(o(t))}else void 0!==t&&e.push(o(t));return e}static _$Eu(t,e){const i=e.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const i of e.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const i=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((i,s)=>{if(e)i.adoptedStyleSheets=s.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of s){const s=document.createElement("style"),r=t.litNonce;void 0!==r&&s.setAttribute("nonce",r),s.textContent=e.cssText,i.appendChild(s)}})(i,this.constructor.elementStyles),i}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$ET(t,e){const i=this.constructor.elementProperties.get(t),s=this.constructor._$Eu(t,i);if(void 0!==s&&!0===i.reflect){const r=(void 0!==i.converter?.toAttribute?i.converter:v).toAttribute(e,i.type);this._$Em=t,null==r?this.removeAttribute(s):this.setAttribute(s,r),this._$Em=null}}_$AK(t,e){const i=this.constructor,s=i._$Eh.get(t);if(void 0!==s&&this._$Em!==s){const t=i.getPropertyOptions(s),r="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:v;this._$Em=s;const o=r.fromAttribute(e,t.type);this[s]=o??this._$Ej?.get(s)??o,this._$Em=null}}requestUpdate(t,e,i,s=!1,r){if(void 0!==t){const o=this.constructor;if(!1===s&&(r=this[t]),i??=o.getPropertyOptions(t),!((i.hasChanged??b)(r,e)||i.useDefault&&i.reflect&&r===this._$Ej?.get(t)&&!this.hasAttribute(o._$Eu(t,i))))return;this.C(t,e,i)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:i,reflect:s,wrapped:r},o){i&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,o??e??this[t]),!0!==r||void 0!==o)||(this._$AL.has(t)||(this.hasUpdated||i||(e=void 0),this._$AL.set(t,e)),!0===s&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,i]of t){const{wrapped:t}=i,s=this[e];!0!==t||this._$AL.has(e)||void 0===s||this.C(e,void 0,i,s)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(t){}firstUpdated(t){}};m.elementStyles=[],m.shadowRootOptions={mode:"open"},m[g("elementProperties")]=new Map,m[g("finalized")]=new Map,f?.({ReactiveElement:m}),(p.reactiveElementVersions??=[]).push("2.1.2");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const $=globalThis,x=t=>t,w=$.trustedTypes,A=w?w.createPolicy("lit-html",{createHTML:t=>t}):void 0,S="$lit$",C=`lit$${Math.random().toFixed(9).slice(2)}$`,k="?"+C,E=`<${k}>`,z=document,N=()=>z.createComment(""),T=t=>null===t||"object"!=typeof t&&"function"!=typeof t,P=Array.isArray,U="[ \t\n\f\r]",H=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,M=/-->/g,R=/>/g,K=RegExp(`>|${U}(?:([^\\s"'>=/]+)(${U}*=${U}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),O=/'/g,L=/"/g,D=/^(?:script|style|textarea|title)$/i,F=t=>(e,...i)=>({_$litType$:t,strings:e,values:i}),I=F(1),B=F(2),j=Symbol.for("lit-noChange"),X=Symbol.for("lit-nothing"),W=new WeakMap,V=z.createTreeWalker(z,129);function Y(t,e){if(!P(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==A?A.createHTML(e):e}const G=(t,e)=>{const i=t.length-1,s=[];let r,o=2===e?"<svg>":3===e?"<math>":"",n=H;for(let e=0;e<i;e++){const i=t[e];let a,l,c=-1,d=0;for(;d<i.length&&(n.lastIndex=d,l=n.exec(i),null!==l);)d=n.lastIndex,n===H?"!--"===l[1]?n=M:void 0!==l[1]?n=R:void 0!==l[2]?(D.test(l[2])&&(r=RegExp("</"+l[2],"g")),n=K):void 0!==l[3]&&(n=K):n===K?">"===l[0]?(n=r??H,c=-1):void 0===l[1]?c=-2:(c=n.lastIndex-l[2].length,a=l[1],n=void 0===l[3]?K:'"'===l[3]?L:O):n===L||n===O?n=K:n===M||n===R?n=H:(n=K,r=void 0);const h=n===K&&t[e+1].startsWith("/>")?" ":"";o+=n===H?i+E:c>=0?(s.push(a),i.slice(0,c)+S+i.slice(c)+C+h):i+C+(-2===c?e:h)}return[Y(t,o+(t[i]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),s]};class q{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let r=0,o=0;const n=t.length-1,a=this.parts,[l,c]=G(t,e);if(this.el=q.createElement(l,i),V.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(s=V.nextNode())&&a.length<n;){if(1===s.nodeType){if(s.hasAttributes())for(const t of s.getAttributeNames())if(t.endsWith(S)){const e=c[o++],i=s.getAttribute(t).split(C),n=/([.?@])?(.*)/.exec(e);a.push({type:1,index:r,name:n[2],strings:i,ctor:"."===n[1]?et:"?"===n[1]?it:"@"===n[1]?st:tt}),s.removeAttribute(t)}else t.startsWith(C)&&(a.push({type:6,index:r}),s.removeAttribute(t));if(D.test(s.tagName)){const t=s.textContent.split(C),e=t.length-1;if(e>0){s.textContent=w?w.emptyScript:"";for(let i=0;i<e;i++)s.append(t[i],N()),V.nextNode(),a.push({type:2,index:++r});s.append(t[e],N())}}}else if(8===s.nodeType)if(s.data===k)a.push({type:2,index:r});else{let t=-1;for(;-1!==(t=s.data.indexOf(C,t+1));)a.push({type:7,index:r}),t+=C.length-1}r++}}static createElement(t,e){const i=z.createElement("template");return i.innerHTML=t,i}}function J(t,e,i=t,s){if(e===j)return e;let r=void 0!==s?i._$Co?.[s]:i._$Cl;const o=T(e)?void 0:e._$litDirective$;return r?.constructor!==o&&(r?._$AO?.(!1),void 0===o?r=void 0:(r=new o(t),r._$AT(t,i,s)),void 0!==s?(i._$Co??=[])[s]=r:i._$Cl=r),void 0!==r&&(e=J(t,r._$AS(t,e.values),r,s)),e}class Z{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??z).importNode(e,!0);V.currentNode=s;let r=V.nextNode(),o=0,n=0,a=i[0];for(;void 0!==a;){if(o===a.index){let e;2===a.type?e=new Q(r,r.nextSibling,this,t):1===a.type?e=new a.ctor(r,a.name,a.strings,this,t):6===a.type&&(e=new rt(r,this,t)),this._$AV.push(e),a=i[++n]}o!==a?.index&&(r=V.nextNode(),o++)}return V.currentNode=z,s}p(t){let e=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class Q{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=X,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=J(this,t,e),T(t)?t===X||null==t||""===t?(this._$AH!==X&&this._$AR(),this._$AH=X):t!==this._$AH&&t!==j&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>P(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==X&&T(this._$AH)?this._$AA.nextSibling.data=t:this.T(z.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:i}=t,s="number"==typeof i?this._$AC(t):(void 0===i.el&&(i.el=q.createElement(Y(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{const t=new Z(s,this),i=t.u(this.options);t.p(e),this.T(i),this._$AH=t}}_$AC(t){let e=W.get(t.strings);return void 0===e&&W.set(t.strings,e=new q(t)),e}k(t){P(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,s=0;for(const r of t)s===e.length?e.push(i=new Q(this.O(N()),this.O(N()),this,this.options)):i=e[s],i._$AI(r),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){const e=x(t).nextSibling;x(t).remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class tt{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,r){this.type=1,this._$AH=X,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=r,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=X}_$AI(t,e=this,i,s){const r=this.strings;let o=!1;if(void 0===r)t=J(this,t,e,0),o=!T(t)||t!==this._$AH&&t!==j,o&&(this._$AH=t);else{const s=t;let n,a;for(t=r[0],n=0;n<r.length-1;n++)a=J(this,s[i+n],e,n),a===j&&(a=this._$AH[n]),o||=!T(a)||a!==this._$AH[n],a===X?t=X:t!==X&&(t+=(a??"")+r[n+1]),this._$AH[n]=a}o&&!s&&this.j(t)}j(t){t===X?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class et extends tt{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===X?void 0:t}}class it extends tt{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==X)}}class st extends tt{constructor(t,e,i,s,r){super(t,e,i,s,r),this.type=5}_$AI(t,e=this){if((t=J(this,t,e,0)??X)===j)return;const i=this._$AH,s=t===X&&i!==X||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,r=t!==X&&(i===X||s);s&&this.element.removeEventListener(this.name,this,i),r&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class rt{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){J(this,t)}}const ot=$.litHtmlPolyfillSupport;ot?.(q,Q),($.litHtmlVersions??=[]).push("3.3.2");const nt=globalThis;
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */class at extends m{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,i)=>{const s=i?.renderBefore??e;let r=s._$litPart$;if(void 0===r){const t=i?.renderBefore??null;s._$litPart$=r=new Q(e.insertBefore(N(),t),t,void 0,i??{})}return r._$AI(t),r})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return j}}at._$litElement$=!0,at.finalized=!0,nt.litElementHydrateSupport?.({LitElement:at});const lt=nt.litElementPolyfillSupport;lt?.({LitElement:at}),(nt.litElementVersions??=[]).push("4.2.2");const ct=((t,...e)=>{const s=1===t.length?t[0]:e.reduce((e,i,s)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[s+1],t[0]);return new r(s,t,i)})`
  /* ============================================
     Host
     ============================================ */
  :host {
    display: block;
    height: 100%;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    line-height: 1.5;
  }

  *, *::before, *::after {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  /* ============================================
     Loading Screen (before hass injected)
     ============================================ */
  .loading-screen {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 100vh;
  }
  .loading-spinner {
    width: 36px;
    height: 36px;
    border: 3px solid var(--divider-color, #e0e0e0);
    border-top-color: var(--primary-color, #03a9f4);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ============================================
     Top Bar (56px, sticky)
     ============================================ */
  .top-bar {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-background-color, #fafafa));
    color: var(--app-header-text-color, var(--primary-text-color, #212121));
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    position: sticky;
    top: 0;
    z-index: 100;
    gap: 12px;
  }

  .menu-btn {
    width: 40px;
    height: 40px;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
    flex-shrink: 0;
  }
  .menu-btn:hover {
    background: var(--secondary-background-color, #e0e0e0);
  }
  .menu-btn svg {
    width: 24px;
    height: 24px;
  }

  .top-bar-title {
    font-size: 20px;
    font-weight: 500;
    flex: 1;
  }

  .top-bar-version {
    font-size: 12px;
    color: var(--secondary-text-color, #757575);
  }

  /* ============================================
     Tabs
     ============================================ */
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    padding: 0 16px;
  }

  .tab {
    padding: 12px 16px;
    border: none;
    background: none;
    color: var(--secondary-text-color, #757575);
    font-size: 14px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .tab:hover {
    color: var(--primary-text-color, #212121);
  }
  .tab.active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }

  /* ============================================
     Content Area
     ============================================ */
  .content {
    padding: 16px;
  }

  /* ============================================
     Guide Card (step list)
     ============================================ */
  .guide-card {
    background: var(--card-background-color, white);
    border-radius: 8px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
    overflow: hidden;
  }

  .step-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .step-item:last-child {
    border-bottom: none;
  }

  .step-number {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, white);
    font-size: 12px;
    font-weight: 500;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .step-content {
    flex: 1;
    min-width: 0;
  }

  .step-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--primary-text-color, #212121);
    margin-bottom: 4px;
  }

  .step-desc {
    font-size: 13px;
    color: var(--secondary-text-color, #757575);
    line-height: 1.4;
  }

  .step-link {
    font-size: 13px;
    color: var(--primary-color, #03a9f4);
    text-decoration: none;
    white-space: nowrap;
    align-self: center;
    flex-shrink: 0;
  }
  .step-link:hover {
    opacity: 0.8;
  }

  /* ============================================
     Info Card (bottom tip)
     ============================================ */
  .info-card {
    margin-top: 16px;
    padding: 12px 16px;
    background: var(--secondary-background-color, #f5f5f5);
    border-radius: 8px;
    font-size: 13px;
    color: var(--secondary-text-color, #757575);
    display: flex;
    gap: 8px;
    align-items: flex-start;
    line-height: 1.4;
  }

  .info-icon {
    color: var(--primary-color, #03a9f4);
    flex-shrink: 0;
  }
  .info-icon svg {
    width: 16px;
    height: 16px;
  }

  /* ============================================
     Editor Card
     ============================================ */
  .editor-card {
    background: var(--card-background-color, white);
    border-radius: 8px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .editor-toolbar {
    display: flex;
    align-items: center;
    height: 48px;
    padding: 0 12px;
    gap: 8px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }

  .file-select {
    padding: 6px 8px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px;
    font-size: 14px;
    background: var(--card-background-color, white);
    color: var(--primary-text-color, #212121);
    flex: 1;
    max-width: 240px;
    outline: none;
  }
  .file-select:focus {
    border-color: var(--primary-color, #03a9f4);
  }

  .icon-btn {
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--secondary-text-color, #757575);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
    font-size: 14px;
    font-weight: 500;
  }
  .icon-btn:hover {
    background: var(--secondary-background-color, #e0e0e0);
  }
  .icon-btn svg {
    width: 20px;
    height: 20px;
  }

  .editor-textarea {
    min-height: 50vh;
    padding: 12px;
    border: none;
    font-family: "Noto Sans Mono", Consolas, monospace;
    font-size: 14px;
    line-height: 1.5;
    color: var(--primary-text-color, #212121);
    background: var(--primary-background-color, #fafafa);
    resize: vertical;
    width: 100%;
    box-sizing: border-box;
    outline: none;
    tab-size: 2;
  }
  .editor-textarea::placeholder {
    color: var(--disabled-text-color, #bdbdbd);
  }

  .editor-statusbar {
    display: flex;
    align-items: center;
    height: 40px;
    padding: 0 12px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
    font-size: 12px;
    color: var(--secondary-text-color, #757575);
    gap: 8px;
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success-color, #4caf50);
  }
  .status-dot.disconnected {
    background: var(--error-color, #f44336);
  }

  .editor-actions {
    margin-left: auto;
    display: flex;
    gap: 8px;
  }

  /* ============================================
     Buttons
     ============================================ */
  .btn {
    padding: 6px 12px;
    border: none;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .btn-primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, white);
  }
  .btn-primary:hover {
    opacity: 0.9;
  }
  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn-secondary {
    background: var(--secondary-background-color, #e0e0e0);
    color: var(--primary-text-color, #212121);
  }
  .btn-secondary:hover {
    background: var(--divider-color, #bdbdbd);
  }
  .btn-danger {
    padding: 8px 16px;
    background: var(--error-color, #f44336);
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .btn-danger:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn-danger:hover:not(:disabled) {
    opacity: 0.9;
  }

  /* ============================================
     Restart Card
     ============================================ */
  .restart-card {
    margin-top: 16px;
    background: var(--card-background-color, white);
    border-radius: 8px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
    padding: 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .restart-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--primary-text-color, #212121);
    margin-right: auto;
  }

  .restart-confirm {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--secondary-text-color, #757575);
    cursor: pointer;
  }
  .restart-confirm input[type="checkbox"] {
    width: 16px;
    height: 16px;
    cursor: pointer;
    accent-color: var(--primary-color, #03a9f4);
  }

  .restart-status {
    width: 100%;
    font-size: 12px;
    margin-top: 4px;
    min-height: 16px;
  }

  /* ============================================
     Responsive (< 600px)
     ============================================ */
  @media (max-width: 600px) {
    .content {
      padding: 8px;
    }
    .tabs {
      padding: 0 8px;
    }
    .editor-textarea {
      min-height: 40vh;
    }
    .restart-card {
      flex-direction: column;
      align-items: flex-start;
    }
  }
`;class dt extends at{static get properties(){return{hass:{type:Object},panel:{type:Object},narrow:{type:Boolean},route:{type:Object},_activeTab:{type:String,state:!0},_files:{type:Array,state:!0},_currentFile:{type:String,state:!0},_editorContent:{type:String,state:!0},_editorDirty:{type:Boolean,state:!0},_fontSize:{type:Number,state:!0},_wsConnected:{type:Boolean,state:!0},_restartConfirmed:{type:Boolean,state:!0},_restartStatus:{type:String,state:!0},_restartStatusColor:{type:String,state:!0},_editorStatus:{type:String,state:!0}}}static get styles(){return ct}constructor(){super(),this._activeTab="guide",this._files=[],this._currentFile="",this._editorContent="",this._editorDirty=!1,this._fontSize=14,this._wsConnected=!1,this._restartConfirmed=!1,this._restartStatus="",this._restartStatusColor="",this._editorStatus="",this._originalContent="",this._hassReady=!1;const t={en:{tab_guide:"Setup Guide",tab_editor:"Editor & System",editor_select_placeholder:"-- Select File --",editor_refresh_title:"Refresh file list",editor_new_file:"+ New",editor_save:"Save",editor_placeholder:"Select a file to start editing...",ws_connected:"Connected",ws_disconnected:"Disconnected",found_files:"Found {0} files",load_failed:"Load failed: {0}",loading_file:"Loading {0}...",loaded_file:"Loaded: {0}",file_load_failed:"Load failed: {0}",confirm_save:"Save changes to {0}?",saving_file:"Saving {0}...",saved_file:"Saved: {0}",save_failed:"Save failed: {0}",new_file_status:"New file: {0} (unsaved)",unsaved_switch:"Unsaved changes will be lost. Switch file?",cache_restored:"Restored unsaved edits",restart_title:"Restart Home Assistant",restart_confirm_label:"I confirm settings are saved and understand restart will interrupt services",restart_btn:"Restart",sending_restart:"Sending restart command...",restart_sent:"Restart sent. Please wait 1-3 minutes.",restart_failed:"Restart failed: {0}"},"zh-Hant":{tab_guide:"設定指南",tab_editor:"編輯器 & 系統",editor_select_placeholder:"-- 選擇檔案 --",editor_refresh_title:"重新整理檔案清單",editor_new_file:"+ 新增",editor_save:"儲存",editor_placeholder:"選擇檔案開始編輯...",ws_connected:"已連線",ws_disconnected:"未連線",found_files:"找到 {0} 個檔案",load_failed:"載入失敗：{0}",loading_file:"正在載入 {0}...",loaded_file:"已載入：{0}",file_load_failed:"載入失敗：{0}",confirm_save:"確定要儲存 {0} 嗎？",saving_file:"正在儲存 {0}...",saved_file:"已儲存：{0}",save_failed:"儲存失敗：{0}",new_file_status:"新檔案：{0}（尚未儲存）",unsaved_switch:"未儲存的變更將會遺失，確定要切換嗎？",cache_restored:"已恢復未儲存的編輯內容",restart_title:"重新啟動 Home Assistant",restart_confirm_label:"我確認已儲存設定，並了解重啟將暫時中斷服務",restart_btn:"重新啟動",sending_restart:"正在發送重啟指令...",restart_sent:"重啟指令已送出，請稍候 1-3 分鐘。",restart_failed:"重啟失敗：{0}"}},e=this.constructor.protocolTranslations;this._translations={en:{...t.en,...e.en},"zh-Hant":{...t["zh-Hant"],...e["zh-Hant"]}},this._handleKeydown=this._onGlobalKeydown.bind(this),this._handleBeforeUnload=this._onBeforeUnload.bind(this)}get _cfg(){return this.constructor.protocolConfig}get _language(){const t=(this.hass?.language||"en").toLowerCase();return"zh-hant"===t||"zh-tw"===t||"zh-hk"===t||t.startsWith("zh")?"zh-Hant":"en"}_t(t,...e){let i=(this._translations[this._language]||this._translations.en)[t]||this._translations.en[t]||t;return e.forEach((t,e)=>{i=i.replace(`{${e}}`,t)}),i}connectedCallback(){super.connectedCallback(),this._restoreFontSize(),this._restoreCache(),window.addEventListener("keydown",this._handleKeydown),window.addEventListener("beforeunload",this._handleBeforeUnload)}disconnectedCallback(){super.disconnectedCallback(),window.removeEventListener("keydown",this._handleKeydown),window.removeEventListener("beforeunload",this._handleBeforeUnload)}updated(t){super.updated(t),t.has("hass")&&this.hass&&!this._hassReady&&(this._hassReady=!0,this._wsConnected=!0,this._editorStatus=this._t("found_files","..."),this._refreshFileList()),t.has("hass")&&this.hass&&(this._wsConnected=!1!==this.hass.connected)}async _callWS(t){if(!this.hass)throw new Error("Not connected");return this.hass.callWS(t)}async _refreshFileList(){try{const t=await this._callWS({type:this._cfg.wsType,action:"list",ext:"yaml",depth:10});this._files=t.files||[],this._editorStatus=this._t("found_files",this._files.length)}catch(t){this._editorStatus=this._t("load_failed",t.message||t)}}async _loadFile(t){if(!t)return this._currentFile="",this._editorContent="",this._originalContent="",this._editorDirty=!1,void(this._editorStatus=this._t("found_files",this._files.length));if(!this._editorDirty||!this._currentFile||confirm(this._t("unsaved_switch")))try{this._editorStatus=this._t("loading_file",t);const e=await this._callWS({type:this._cfg.wsType,action:"load",path:t});this._editorContent=e.content,this._originalContent=e.content,this._currentFile=e.path||t,this._editorDirty=!1,this._editorStatus=this._t("loaded_file",this._currentFile),this._cacheState()}catch(t){this._editorStatus=this._t("file_load_failed",t.message||t)}}async _saveFile(){if(this._currentFile&&confirm(this._t("confirm_save",this._currentFile))){this._editorStatus=this._t("saving_file",this._currentFile);try{await this._callWS({type:this._cfg.wsType,action:"save",path:this._currentFile,content:this._editorContent}),this._originalContent=this._editorContent,this._editorDirty=!1,this._editorStatus=this._t("saved_file",this._currentFile),this._cacheState()}catch(t){this._editorStatus=this._t("save_failed",t.message||t)}}}_newFile(){const t=prompt(this._t("new_file_prompt"),this._cfg.defaultNewFile);if(!t)return;let e=t.replace(/\.\./g,"").trim();e.endsWith(".yaml")||e.endsWith(".yml")||(e+=".yaml"),this._files.includes(e)||(this._files=[...this._files,e]),this._currentFile=e,this._editorContent="",this._originalContent="",this._editorDirty=!0,this._editorStatus=this._t("new_file_status",e)}_changeFontSize(t){this._fontSize=Math.max(10,Math.min(24,this._fontSize+t));try{localStorage.setItem(`${this._cfg.localStoragePrefix}_fontsize`,this._fontSize)}catch(t){}}_restoreFontSize(){try{const t=localStorage.getItem(`${this._cfg.localStoragePrefix}_fontsize`);t&&(this._fontSize=parseInt(t,10)||14)}catch(t){}}_cacheState(){try{localStorage.setItem(`${this._cfg.localStoragePrefix}_cache`,JSON.stringify({file:this._currentFile,content:this._editorContent,dirty:this._editorDirty,ts:Date.now()}))}catch(t){}}_restoreCache(){try{const t=localStorage.getItem(`${this._cfg.localStoragePrefix}_cache`);if(!t)return;const e=JSON.parse(t);e.dirty&&e.content&&Date.now()-e.ts<36e5&&(this._editorContent=e.content,this._currentFile=e.file||"",this._editorDirty=!0,this._editorStatus=this._t("cache_restored"))}catch(t){}}_onGlobalKeydown(t){(t.ctrlKey||t.metaKey)&&"s"===t.key&&(t.preventDefault(),this._currentFile&&"editor"===this._activeTab&&this._saveFile())}_onBeforeUnload(t){this._editorDirty&&(t.preventDefault(),t.returnValue="")}_onEditorInput(t){this._editorContent=t.target.value,this._editorDirty=this._editorContent!==this._originalContent,this._cacheState()}_onEditorKeydown(t){if("Tab"===t.key){t.preventDefault();const e=t.target,i=e.selectionStart,s=e.selectionEnd;e.value=e.value.substring(0,i)+"  "+e.value.substring(s),e.selectionStart=e.selectionEnd=i+2,this._editorContent=e.value,this._editorDirty=!0,this._cacheState()}}_onFileSelect(t){this._loadFile(t.target.value)}_toggleRestart(t){this._restartConfirmed=t.target.checked}async _restartHA(){this._restartConfirmed=!1,this._restartStatus=this._t("sending_restart"),this._restartStatusColor="var(--warning-color, #ff9800)";try{await this.hass.callService("homeassistant","restart"),this._restartStatus=this._t("restart_sent"),this._restartStatusColor="var(--success-color, #4caf50)"}catch(t){this._restartStatus=this._t("restart_failed",t.message||t),this._restartStatusColor="var(--error-color, #f44336)"}}_switchTab(t){this._activeTab=t}_toggleMenu(){this.dispatchEvent(new Event("hass-toggle-menu",{bubbles:!0,composed:!0}))}get _iconMenu(){return B`<path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" fill="currentColor"/>`}get _iconRefresh(){return B`<path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" fill="currentColor"/>`}get _iconInfo(){return B`<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z" fill="currentColor"/>`}render(){if(!this.hass)return I`<div class="loading-screen"><div class="loading-spinner"></div></div>`;const t=this._cfg;return I`
      <!-- Top Bar -->
      <div class="top-bar">
        <button class="menu-btn" @click=${this._toggleMenu}>
          <svg viewBox="0 0 24 24">${this._iconMenu}</svg>
        </button>
        <span class="top-bar-title">${this._t("panel_title")}</span>
        <span class="top-bar-version">v${t.version}</span>
      </div>

      <!-- Tabs -->
      <div class="tabs">
        <button
          class="tab ${"guide"===this._activeTab?"active":""}"
          @click=${()=>this._switchTab("guide")}
        >${this._t("tab_guide")}</button>
        <button
          class="tab ${"editor"===this._activeTab?"active":""}"
          @click=${()=>this._switchTab("editor")}
        >${this._t("tab_editor")}</button>
      </div>

      <!-- Content -->
      <div class="content">
        ${"guide"===this._activeTab?this._renderGuide():this._renderEditorTab()}
      </div>
    `}_renderGuide(){const t=this._cfg,e=t.guideSteps||[];return I`
      <div class="guide-card">
        ${e.map((t,e)=>I`
            <div class="step-item">
              <span class="step-number">${e+1}</span>
              <div class="step-content">
                <div class="step-title">${this._t(t.titleKey)}</div>
                <div class="step-desc">${this._t(t.descKey)}</div>
              </div>
              ${t.linkKey?I`<a class="step-link" href=${t.url} target="_blank" rel="noopener">${this._t(t.linkKey)}</a>`:""}
            </div>
          `)}
      </div>

      ${t.infoTip?I`
            <div class="info-card">
              <span class="info-icon">
                <svg viewBox="0 0 24 24">${this._iconInfo}</svg>
              </span>
              <span>${this._t(t.infoTip)}</span>
            </div>
          `:""}
    `}_renderEditorTab(){return I`
      <!-- Editor Card -->
      <div class="editor-card">
        <div class="editor-toolbar">
          <select class="file-select" @change=${this._onFileSelect}>
            <option value="">${this._t("editor_select_placeholder")}</option>
            ${this._files.map(t=>I`<option value=${t} ?selected=${t===this._currentFile}>${t}</option>`)}
          </select>
          <button class="icon-btn" @click=${this._refreshFileList} title=${this._t("editor_refresh_title")}>
            <svg viewBox="0 0 24 24">${this._iconRefresh}</svg>
          </button>
          <button class="icon-btn" @click=${()=>this._changeFontSize(-1)} title="A-">A-</button>
          <button class="icon-btn" @click=${()=>this._changeFontSize(1)} title="A+">A+</button>
        </div>

        <textarea
          class="editor-textarea"
          .value=${this._editorContent}
          @input=${this._onEditorInput}
          @keydown=${this._onEditorKeydown}
          style="font-size:${this._fontSize}px"
          placeholder=${this._t("editor_placeholder")}
          spellcheck="false"
        ></textarea>

        <div class="editor-statusbar">
          <span class="status-dot ${this._wsConnected?"":"disconnected"}"></span>
          <span>${this._wsConnected?this._t("ws_connected"):this._t("ws_disconnected")}</span>
          <span>\u00b7</span>
          <span>${this._editorStatus}</span>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click=${this._newFile}>${this._t("editor_new_file")}</button>
            <button class="btn btn-primary" ?disabled=${!this._currentFile} @click=${this._saveFile}>${this._t("editor_save")}</button>
          </div>
        </div>
      </div>

      <!-- Restart Card -->
      <div class="restart-card">
        <span class="restart-title">${this._t("restart_title")}</span>
        <label class="restart-confirm">
          <input type="checkbox" .checked=${this._restartConfirmed} @change=${this._toggleRestart} />
          ${this._t("restart_confirm_label")}
        </label>
        <button class="btn-danger" ?disabled=${!this._restartConfirmed} @click=${this._restartHA}>
          ${this._t("restart_btn")}
        </button>
        ${this._restartStatus?I`<span class="restart-status" style="color:${this._restartStatusColor}">${this._restartStatus}</span>`:""}
      </div>
    `}}const ht={domain:"woow_knx",wsType:"woow_knx/ws",configSubdir:"knx",protocolLabel:"KNX",defaultNewFile:"knx_config.yaml",localStoragePrefix:"woow_knx",version:"2.1.0",officialDocsUrl:"https://www.home-assistant.io/integrations/knx",woowAiUrl:"https://aiot.woowtech.io/blog",infoTip:"info_tip",guideSteps:[{titleKey:"step1_title",descKey:"step1_desc",linkKey:"step1_link",url:"https://www.home-assistant.io/integrations/knx"},{titleKey:"step2_title",descKey:"step2_desc",linkKey:"step2_link",url:"https://aiot.woowtech.io/blog"},{titleKey:"step3_title",descKey:"step3_desc"},{titleKey:"step4_title",descKey:"step4_desc"},{titleKey:"step5_title",descKey:"step5_desc"}]},pt={en:{panel_title:"KNX Settings",step1_title:"Read Official Documentation",step1_desc:"Review the HA KNX integration docs to understand connection settings, group addresses, and supported entity types.",step1_link:"KNX Docs",step2_title:"Use Woow AI Assistant",step2_desc:"Provide your device model and group addresses to the AI assistant to generate ready-to-use YAML configurations.",step2_link:"AI Assistant",step3_title:"Add KNX Integration via UI",step3_desc:"Go to Settings > Devices & Services > Add Integration, search for KNX, and configure your gateway connection.",step4_title:"Edit YAML Configuration",step4_desc:"Use the built-in editor to write or paste your KNX device YAML configuration.",step5_title:"Restart & Verify",step5_desc:"Restart Home Assistant, then check Settings > Devices & Services > KNX to confirm devices loaded correctly.",info_tip:"KNX connection settings are configured via UI. YAML is only used for device and entity definitions.",editor_placeholder:"Select a file above to start editing, or paste AI-generated KNX YAML...",new_file_prompt:"Enter new file name (saved in config/knx/ directory):"},"zh-Hant":{panel_title:"KNX 設定",step1_title:"閱讀官方文檔",step1_desc:"瀏覽 HA KNX 整合文檔，了解連線設定、群組地址與支援的實體類型。",step1_link:"KNX 文檔",step2_title:"使用 Woow AI 助手",step2_desc:"提供裝置型號與群組地址給 AI 助手，即可取得可直接使用的 YAML 設定。",step2_link:"AI 助手",step3_title:"透過 UI 新增 KNX 整合",step3_desc:"前往 設定 > 裝置與服務 > 新增整合，搜尋 KNX 並設定 Gateway 連線。",step4_title:"編輯 YAML 設定",step4_desc:"使用內建編輯器撰寫或貼上 KNX 裝置 YAML 設定。",step5_title:"重啟並驗證",step5_desc:"重新啟動 Home Assistant，然後至 設定 > 裝置與服務 > KNX 確認裝置已載入。",info_tip:"KNX 連線設定透過 UI 完成，YAML 僅用於定義裝置與實體。",editor_placeholder:"選擇上方檔案開始編輯，或直接貼上 AI 產出的 KNX YAML 設定...",new_file_prompt:"請輸入新檔案名稱（儲存於 config/knx/ 目錄下）："}};customElements.define("woow-knx-panel",class extends dt{static get protocolConfig(){return ht}static get protocolTranslations(){return pt}});
