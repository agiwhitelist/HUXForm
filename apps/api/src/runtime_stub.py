"""The window.agui runtime stub injected into every generated document.

The iframe runs with sandbox="allow-scripts" (NO same-origin). Everything
flows through postMessage to the parent shell, which proxies tool calls
and event subscription to the AGUI backend.
"""

RUNTIME_STUB = """<script>(function(){
  if (window.agui) return;
  var pending = {};
  var nextId = 1;
  var listeners = [];
  var stateSnapshot = {};
  function send(msg){ parent.postMessage(Object.assign({__agui:true}, msg), '*'); }
  function call(name, params){
    return new Promise(function(resolve, reject){
      var id = 'c' + (nextId++);
      pending[id] = { resolve: resolve, reject: reject };
      send({ kind:'call', id: id, name: name, params: params || {} });
    });
  }
  function fanout(ev){
    if (ev && ev.type === 'state_patch' && ev.patch) {
      Object.assign(stateSnapshot, ev.patch);
    }
    if (ev && ev.type === 'research_done' && window.agui) {
      var existing = window.agui.research || { summary: '', steps: [], stopped: '' };
      window.agui.research = {
        summary: typeof ev.summary === 'string' ? ev.summary : (existing.summary || ''),
        steps:   Array.isArray(existing.steps) ? existing.steps : [],
        stopped: typeof ev.stopped === 'string' ? ev.stopped : (existing.stopped || ''),
      };
    }
    if (ev && ev.type === 'research_step' && window.agui) {
      var r = window.agui.research || { summary: '', steps: [], stopped: 'in_progress' };
      if (!Array.isArray(r.steps)) r.steps = [];
      r.steps.push({
        tool: ev.tool, params: ev.params_preview, reason: ev.reason,
        ok: false, result: null, error: null,
      });
      window.agui.research = r;
    }
    if (ev && ev.type === 'file_attached' && ev.file && window.agui) {
      var files = window.agui.files || [];
      var exists = false;
      for (var j = 0; j < files.length; j++) {
        if (files[j] && files[j].id === ev.file.id) { exists = true; break; }
      }
      if (!exists) {
        files.push(ev.file);
        window.agui.files = files;
      }
    }
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](ev); } catch (err) {}
    }
  }
  window.addEventListener('message', function(e){
    var d = e.data;
    if (!d || !d.__agui) return;
    if (d.kind === 'boot') {
      window.agui.plan = d.plan || null;
      window.agui.tools = d.tools || [];
      window.agui.goal = d.goal || '';
      window.agui.taskId = d.taskId || '';
      window.agui.files = d.files || [];
      window.agui.research = d.research || { summary: '', steps: [], stopped: '' };
      var hist = d.history || [];
      for (var i = 0; i < hist.length; i++) fanout(hist[i]);
      window.dispatchEvent(new CustomEvent('agui:boot', { detail: d }));
    } else if (d.kind === 'event') {
      fanout(d.event);
    } else if (d.kind === 'response') {
      var p = pending[d.id];
      if (!p) return;
      delete pending[d.id];
      if (d.ok) p.resolve(d.result); else p.reject(new Error(d.error || 'tool error'));
    }
  });
  function upload(file){
    return new Promise(function(resolve, reject){
      if (!file) { reject(new Error('uploadFile: no file')); return; }
      var id = 'u' + (nextId++);
      pending[id] = { resolve: resolve, reject: reject };
      send({
        kind: 'upload',
        id: id,
        file: file,
        name: file.name || 'upload',
        mime: file.type || 'application/octet-stream',
        size: file.size || 0,
      });
    });
  }
  window.agui = {
    plan: null, tools: [], goal: '', taskId: '', files: [],
    research: { summary: '', steps: [], stopped: '' },
    callTool: call,
    setState: function(patch){ return call('task.set_state', { patch: patch }); },
    getState: function(){ return Object.assign({}, stateSnapshot); },
    finalResult: function(value){ return call('task.final_result', { result: value }); },
    log: function(level, message){ return call('task.log', { level: level || 'info', message: String(message) }); },
    readFile: function(file_id){ return call('files.read', { file_id: file_id }); },
    uploadFile: upload,
    onEvent: function(handler){
      listeners.push(handler);
      return function(){ var i = listeners.indexOf(handler); if (i>=0) listeners.splice(i,1); };
    },
    askApproval: function(label, details){
      return new Promise(function(resolve){
        var id = 'a' + (nextId++);
        pending[id] = {
          resolve: function(r){ resolve(!!(r && r.approved)); },
          reject: function(){ resolve(false); }
        };
        send({ kind:'approval', id: id, label: String(label||''), details: details||null });
      });
    },
    toast: function(message, kind){
      var t = document.createElement('div');
      t.textContent = String(message);
      t.style.cssText = 'position:fixed;right:16px;bottom:16px;padding:10px 14px;border-radius:10px;'+
        'background:'+(kind==='error'?'#5b1f1f':(kind==='success'?'#1f4d2e':'#1c2230'))+
        ';color:#fff;font:13px ui-sans-serif,system-ui,sans-serif;z-index:99999;box-shadow:0 8px 24px rgba(0,0,0,.4);';
      document.body.appendChild(t);
      setTimeout(function(){ t.style.transition='opacity .4s'; t.style.opacity='0'; }, 2200);
      setTimeout(function(){ t.remove(); }, 2700);
    },
  };
  // Intercept fetch() to /api/* and reroute through the bridge.
  // Generated UIs sometimes try fetch directly — the sandboxed iframe has
  // no same-origin and would fail. We catch /api/files (FormData uploads),
  // /api/turns/{tid}/files (attach), /api/turns/{tid}/tools/{name} (tool
  // calls) and resolve them as if the UI had used agui.uploadFile /
  // agui.callTool.
  if (window.fetch) {
    var __origFetch = window.fetch.bind(window);
    window.fetch = function(input, init){
      try {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        // Normalise so absolute, relative and Request inputs all match
        var pathOnly = url;
        var m1 = String(url).match(/^https?:\/\/[^\/]+(\/.*)$/i);
        if (m1) pathOnly = m1[1];
        if (typeof pathOnly === 'string' && pathOnly.indexOf('/api/') === 0) {
          // Upload: /api/files
          if (/^\/api\/files\/?$/.test(pathOnly) && init && init.method && init.method.toUpperCase() === 'POST') {
            var body = init.body;
            var file = null;
            if (body && typeof body.get === 'function') file = body.get('file');
            if (!file && body && body.append) {
              try { body.entries(); } catch(_) {}
            }
            if (file) {
              return upload(file).then(function(rec){
                return new Response(JSON.stringify({ file: rec }), {
                  status: 200,
                  headers: { 'content-type': 'application/json' },
                });
              }).catch(function(err){
                return new Response(JSON.stringify({ detail: String(err) }), {
                  status: 500,
                  headers: { 'content-type': 'application/json' },
                });
              });
            }
          }
          // Tool call: /api/turns/{tid}/tools/{name}
          var m = pathOnly.match(/^\/api\/turns\/[^\/]+\/tools\/(.+)$/);
          if (m && init && init.method && init.method.toUpperCase() === 'POST') {
            var params = {};
            try { params = JSON.parse(init.body || '{}'); } catch(_){}
            return call(m[1], params).then(function(result){
              return new Response(JSON.stringify({ result: result }), {
                status: 200,
                headers: { 'content-type': 'application/json' },
              });
            }).catch(function(err){
              return new Response(JSON.stringify({ detail: String(err) }), {
                status: 500,
                headers: { 'content-type': 'application/json' },
              });
            });
          }
        }
      } catch (e) {}
      return __origFetch(input, init);
    };
  }

  send({ kind:'ready' });
})();</script>"""


def inject_runtime(html: str) -> str:
    if not html:
        return RUNTIME_STUB
    lower = html.lower()
    idx = lower.find("<head>")
    if idx != -1:
        cut = idx + len("<head>")
        return html[:cut] + "\n" + RUNTIME_STUB + html[cut:]
    idx = lower.find("<head ")
    if idx != -1:
        end = html.find(">", idx)
        if end != -1:
            return html[: end + 1] + "\n" + RUNTIME_STUB + html[end + 1 :]
    idx = lower.find("<body")
    if idx != -1:
        return html[:idx] + RUNTIME_STUB + html[idx:]
    return RUNTIME_STUB + html
