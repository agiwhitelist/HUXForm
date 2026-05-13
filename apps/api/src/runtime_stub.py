"""The window.agui runtime stub injected into every generated document.

The generated UI is sandboxed (allow-scripts, NOT allow-same-origin), so
this stub talks to the parent frame purely via postMessage. The parent
(apps/web bridge.ts) routes those messages to the AGUI backend.
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
  window.addEventListener('message', function(e){
    var d = e.data;
    if (!d || !d.__agui) return;
    if (d.kind === 'boot') {
      window.agui.plan = d.plan || null;
      window.agui.tools = d.tools || [];
      window.agui.goal = d.goal || '';
      window.agui.taskId = d.taskId || '';
      var hist = d.history || [];
      for (var i = 0; i < hist.length; i++) {
        var ev = hist[i];
        if (ev && ev.type === 'state_patch' && ev.patch) {
          Object.assign(stateSnapshot, ev.patch);
        }
        for (var j = 0; j < listeners.length; j++) {
          try { listeners[j](ev); } catch (err) {}
        }
      }
      window.dispatchEvent(new CustomEvent('agui:boot', { detail: d }));
    } else if (d.kind === 'event') {
      var ev2 = d.event;
      if (ev2 && ev2.type === 'state_patch' && ev2.patch) {
        Object.assign(stateSnapshot, ev2.patch);
      }
      for (var k = 0; k < listeners.length; k++) {
        try { listeners[k](ev2); } catch (err) {}
      }
    } else if (d.kind === 'response') {
      var p = pending[d.id];
      if (!p) return;
      delete pending[d.id];
      if (d.ok) p.resolve(d.result); else p.reject(new Error(d.error || 'tool error'));
    }
  });
  window.agui = {
    plan: null, tools: [], goal: '', taskId: '',
    callTool: call,
    setState: function(patch){ return call('task.set_state', { patch: patch }); },
    getState: function(){ return Object.assign({}, stateSnapshot); },
    finalResult: function(value){ return call('task.final_result', { result: value }); },
    log: function(level, message){ return call('task.log', { level: level || 'info', message: String(message) }); },
    onEvent: function(handler){
      listeners.push(handler);
      return function(){ var i = listeners.indexOf(handler); if (i>=0) listeners.splice(i,1); };
    },
    askApproval: function(label, details){
      return new Promise(function(resolve){
        var id = 'a' + (nextId++);
        pending[id] = { resolve: function(r){ resolve(!!(r && r.approved)); }, reject: function(){ resolve(false); } };
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
  send({ kind:'ready' });
})();</script>"""


def inject_runtime(html: str) -> str:
    """Insert the runtime stub right after <head>, or fall back to prepend."""
    if not html:
        return RUNTIME_STUB
    lower = html.lower()
    idx = lower.find("<head>")
    if idx != -1:
        cut = idx + len("<head>")
        return html[:cut] + "\n" + RUNTIME_STUB + html[cut:]
    idx = lower.find("<head ")  # <head attr=...>
    if idx != -1:
        end = html.find(">", idx)
        if end != -1:
            return html[: end + 1] + "\n" + RUNTIME_STUB + html[end + 1 :]
    # No <head> tag — inject before <body> or at the top
    idx = lower.find("<body")
    if idx != -1:
        return html[:idx] + RUNTIME_STUB + html[idx:]
    return RUNTIME_STUB + html
