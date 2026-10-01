let docHref=img.ownerDocument.defaultView.location.href;if(docHref.startsWith("about:")){docHref=window.location.href;}
const srcUrl=new URL(src,docHref);const relativeSrc=srcUrl.pathname;
