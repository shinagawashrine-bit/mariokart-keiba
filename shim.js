// claude.ai 版と同じアプリ本体を、一般のWeb＋Firebase で動かすための橋渡し。
// アプリは claude.use("db" | "user" | "downloads") を呼ぶので、それを Firebase などで用意する。
(function(){
  var cfg = window.MK_CONFIG || {};
  var ls = {
    get: function(k){ try{ return localStorage.getItem(k); }catch(e){ return null; } },
    set: function(k,v){ try{ localStorage.setItem(k,v); }catch(e){} }
  };
  window.MK_WEB = {
    checkPin: function(p){
      if(cfg.adminPin && String(p).trim() === String(cfg.adminPin)){ ls.set("mk_admin","1"); return true; }
      return false;
    }
  };

  // この端末のID（スマホごとに「誰の端末か」を覚えるため）
  var dev = ls.get("mk_device");
  if(!dev){ dev = "d" + Math.random().toString(36).slice(2,12) + Math.random().toString(36).slice(2,6); ls.set("mk_device", dev); }

  var fs = null;
  try{
    if(cfg.firebase && cfg.firebase.apiKey && window.firebase){
      if(!firebase.apps.length) firebase.initializeApp(cfg.firebase);
      fs = firebase.firestore();
    }
  }catch(e){ console.error(e); fs = null; }

  function snap(s){ return { id: s.id, exists: !!s.exists, data: function(){ return s.data(); }, metadata: s.metadata || {} }; }
  function err(e){ return function(x){ console.error(x); if(e) e({ code: "unavailable", message: String(x && x.message || x) }); }; }
  function wrapDoc(r){
    return {
      id: r.id, path: r.path,
      get: function(){ return r.get().then(snap); },
      set: function(d){ return r.set(d); },
      update: function(d){ return r.update(d); },
      delete: function(){ return r.delete(); },
      onSnapshot: function(n, e){ return r.onSnapshot(function(s){ n(snap(s)); }, err(e)); }
    };
  }
  function wrapCol(c){
    return {
      path: c.path,
      doc: function(id){ return wrapDoc(id ? c.doc(id) : c.doc()); },
      onSnapshot: function(n, e){ return c.onSnapshot(function(q){ var d = q.docs.map(snap); n({ docs: d, size: d.length, empty: !d.length }); }, err(e)); }
    };
  }
  var db = fs ? { doc: function(p){ return wrapDoc(fs.doc(p)); }, collection: function(p){ return wrapCol(fs.collection(p)); } } : null;

  var user = {
    id: function(){ return Promise.resolve(dev); },
    isOwner: function(){ return Promise.resolve(ls.get("mk_admin") === "1"); },
    canEdit: function(){ return Promise.resolve(ls.get("mk_admin") === "1"); },
    can: function(){ return Promise.resolve(true); }
  };

  var downloads = {
    save: function(o){
      return new Promise(function(res){
        var blob = new Blob([o.data], { type: /\.csv$/.test(o.filename) ? "text/csv" : "application/octet-stream" });
        var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = o.filename;
        document.body.appendChild(a); a.click(); setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 1000); res();
      });
    }
  };

  window.claude = { use: function(name){
    return Promise.resolve(name === "db" ? db : name === "user" ? user : name === "downloads" ? downloads : null);
  } };
})();
