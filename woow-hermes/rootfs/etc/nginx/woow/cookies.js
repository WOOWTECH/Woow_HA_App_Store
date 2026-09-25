// Session cookies on the ingress path get their own names.
//
// Browsers do not scope cookies by port. A login on the LAN port
// (http://<ha-ip>:9119, Path=/) is therefore also sent to
// http://<ha-ip>:8123/api/hassio_ingress/<token>/..., where Hermes would accept
// it: the sidebar is logged in without its own login, and its logout does not
// stick. Renaming the ingress path's hermes_* cookies, and dropping every
// hermes_* cookie that arrives under its upstream name, keeps the two entrances
// as separate as they are on different hosts.

var OURS = /^(__Secure-|__Host-)?woowing_(hermes_[A-Za-z0-9_]+)$/;
var HERMES = /^(__Secure-|__Host-)?hermes_[A-Za-z0-9_]+$/;

// Cookie header sent to Hermes: our names mapped back, foreign hermes_* dropped.
function request_cookie(r) {
    var raw = r.headersIn.Cookie;
    if (!raw) {
        return "";
    }
    var out = [];
    raw.split(";").forEach(function (part) {
        var s = part.trim();
        if (!s) {
            return;
        }
        var eq = s.indexOf("=");
        var name = eq < 0 ? s : s.slice(0, eq);
        var rest = eq < 0 ? "" : s.slice(eq);
        var m = OURS.exec(name);
        if (m) {
            out.push((m[1] || "") + m[2] + rest);
        } else if (!HERMES.test(name)) {
            out.push(s);
        }
    });
    return out.join("; ");
}

// Set-Cookie from Hermes: hermes_* becomes woowing_hermes_*, keeping any
// __Secure-/__Host- prefix in front where browsers require it.
function rename_set_cookie(r) {
    var h = r.headersOut["Set-Cookie"];
    if (!h || !h.length) {
        return;
    }
    r.headersOut["Set-Cookie"] = h.map(function (c) {
        return c.replace(/^(__Secure-|__Host-)?(hermes_[A-Za-z0-9_]+=)/, function (all, p, n) {
            return (p || "") + "woowing_" + n;
        });
    });
}

export default { request_cookie, rename_set_cookie };
