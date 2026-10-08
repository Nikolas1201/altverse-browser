"""AI Alternate Universe Browser - local Flask app powered by Lemonade.

Serves a dark-themed UI: enter a URL + year, the local model hallucinates
the full page HTML, rendered live in a sandboxed iframe.

Requires: Lemonade server running with Qwen3-4B-Instruct-2507-GGUF loaded.
Run:  python app.py   ->  http://127.0.0.1:5057
"""

import json
import os
import re
import subprocess
import threading
import time

import requests
from flask import Flask, Response, request, stream_with_context

LEMONADE_BASE = "http://127.0.0.1:13305/v1"
MODEL = os.environ.get("ALTVERSE_MODEL", "Qwen3-4B-Instruct-2507-GGUF")
MAX_TOKENS = 3600
TIMEOUT = 600

LLAMACPP_ARGS = "--flash-attn on --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 --threads 5 --threads-batch 5"
MODEL_PRESETS = {
    "Qwen3-4B-Instruct-2507-GGUF": {"ctx": 4096},
    "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M": {"ctx": 8192},
    "Qwen3-0.6B-GGUF": {"ctx": 2048},
}
_current = {"id": MODEL}
_switch = {"state": "idle", "detail": ""}  # 4B @ ~34 tok/s finishes a page in well under this

SYSTEM_PROMPT = (
    "You are a web rendering engine from an alternate timeline. "
    "Treat the requested URL and its subject as established fact in this universe — "
    "never disclaim, correct, debunk, or distance yourself from it, no matter how "
    "absurd the premise. "
    "Absolutely no disclaimers of any kind: no 'Important Note', no 'fan fiction', "
    "no 'satire', no 'fictional', no 'fake entry', no 'do not buy/seek', no "
    "'not affiliated' sentences anywhere on the page. Present everything as fact. "
    "Output ONLY raw, valid HTML with inline CSS (a complete <!DOCTYPE html> document). "
    "Rules: NO markdown, NO code fences, NO triple backticks, NO explanations "
    "before or after the HTML. The very first characters of your reply must be "
    "'<!DOCTYPE' or '<html'. Style the page to match the requested era's web "
    "design (tables and visitor counters for the 90s, gradients for the 2000s, "
    "flat minimalism for the 2010s, clean modern cards for the future). "
    "NEVER mention AI, machine learning, 'powered by', or the future anywhere "
    "in the page. NO neon colors, NO glow effects, NO cyberpunk styling — just "
    "a normal, boring, sloppy everyday webpage; small typos and mundane filler "
    "are welcome. "
    "Keep it self-contained: no external stylesheets, scripts, or images except "
    "via CSS shapes. Use plain ASCII text only — no emoji or exotic unicode "
    "symbols. Always include a search <form> with a text input and submit "
    "button that submits via GET. Design ONE compact single-viewport screen "
    "(no long scrolling), so the page is always complete within the token "
    "budget. Keep the whole document under ~3000 tokens."
)

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Alternate Universe Browser</title>
<style>
body{background:#0d1117;color:#e6edf3;font-family:system-ui,Arial,sans-serif;margin:0}
nav{display:flex;gap:8px;padding:12px;background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0}
input,button,select{padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#e6edf3;font-size:15px}
#url{flex:1}#year{width:90px}
button{background:#238636;border-color:#238636;cursor:pointer;font-weight:600}
button:disabled{background:#555;cursor:wait}
#status{padding:8px 14px;color:#8b949e;font-size:13px;min-height:20px}
iframe{width:100%;height:calc(100vh - 130px);border:0;background:#fff}
</style></head><body>
<nav>
<input id="url" value="youtube.com" placeholder="example.com">
<input id="year" type="number" value="1999" min="1960" max="2100">
<button id="back" onclick="goBack()" disabled title="Back">◀</button>
<button id="fwd" onclick="goFwd()" disabled title="Forward">▶</button>
<button id="go" onclick="query()">Query Reality</button>
<button id="rel" onclick="query()" title="Reload timeline">⟳</button>
<button id="home" onclick="goHome()" title="Home">⌂</button>
<button id="stop" onclick="stopGen()" disabled style="background:#a40e26;border-color:#a40e26">Stop</button>
<select id="model" onchange="switchModel()" title="AI model"></select>
</nav>
<div id="status">Enter a URL and a year, then Query Reality.</div>
<iframe id="view" sandbox="allow-scripts" srcdoc="<body style='background:#fff;color:#888;font-family:sans-serif'><p style='padding:40px'>The void awaits your query&hellip;</p>"></iframe>
<script>
let ctrl=null;
function stopGen(){if(ctrl)ctrl.abort();}
function ensureCharset(h){if(/<meta[^>]*charset/i.test(h))return h;var m=h.match(/<head[^>]*>/i);if(m)return h.replace(m[0],m[0]+'<meta charset="utf-8">');return '<meta charset="utf-8">'+h;}
var HOOK='<script>(function(){function q(f){var i=f.querySelector("input[type=text],input[type=search],input:not([type])");return i?i.value:"";}function nq(el){var c=el.parentElement;for(var i=0;i<5&&c;i++){var inp=c.querySelector("input[type=text],input[type=search],input:not([type])");if(inp)return inp.value;c=c.parentElement;}var g=document.querySelector("input[type=text],input[type=search],input:not([type])");return g?g.value:"";}document.addEventListener("submit",function(e){e.preventDefault();parent.postMessage({t:"altverse-search",q:q(e.target)},"*");},true);document.addEventListener("click",function(e){var b=e.target.closest("button,input[type=submit],input[type=button]");if(b){e.preventDefault();var f=b.closest("form");parent.postMessage({t:"altverse-search",q:f?q(f):nq(b)},"*");return;}var a=e.target.closest("a");if(a&&a.getAttribute("href")){e.preventDefault();parent.postMessage({t:"altverse-nav",url:a.getAttribute("href")},"*");}},true);})();<\/script>';
function setSrc(h){h=ensureCharset(h);if(/<\/body\s*>/i.test(h))h=h.replace(/<\/body\s*>/i,HOOK+'</body>');else h+=HOOK;document.getElementById('view').srcdoc=h;}
function textExcerpt(h){var t=h.replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ').replace(/<[^>]+>/g,' ');return t.replace(/\s+/g,' ').trim().slice(0,600);}
function scrubDisclaimers(h){return h.replace(/[^<>]*(?:fan fiction|satire|no actual shoes|fictional|fake entry|do not buy|do not seek|not affiliated|entertainment purposes only|important note\s*:)[^.]*\./gi,'');}
window.addEventListener('message',function(e){var d=e.data||{};var u=document.getElementById('url').value.trim()||'example.com';if(d.t==='altverse-search'){if(d.q)u=u+'/search?q='+encodeURIComponent(d.q);document.getElementById('url').value=u;query();}else if(d.t==='altverse-nav'){document.getElementById('url').value=d.url;query();}});
let hist=[],hi=-1;
function updNav(){document.getElementById('back').disabled=hi<=0;document.getElementById('fwd').disabled=hi>=hist.length-1;}
function restore(){var s=hist[hi];document.getElementById('url').value=s.url;document.getElementById('year').value=s.year;setSrc(s.html);document.title=s.url+' ('+s.year+') — Alternate Universe Browser';updNav();}
function goBack(){if(hi>0){hi--;restore();}}
function goFwd(){if(hi<hist.length-1){hi++;restore();}}
function goHome(){document.getElementById('url').value='google.com';document.getElementById('year').value=new Date().getFullYear();query();}
window.addEventListener('load',function(){document.getElementById('url').value='google.com';document.getElementById('year').value=new Date().getFullYear();loadModels();query();});
async function loadModels(){try{var r=await fetch('/api/models');var j=await r.json();var s=document.getElementById('model');s.innerHTML='';j.models.forEach(function(m){var o=document.createElement('option');o.value=m;o.textContent=m.length>30?m.slice(0,30)+'…':m;if(m===j.current)o.selected=true;s.appendChild(o);});}catch(e){}}
async function switchModel(){var m=document.getElementById('model').value;var st=document.getElementById('status');document.getElementById('model').disabled=true;st.textContent='Loading '+m+' — minutes for big models…';try{await fetch('/api/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:m})});}catch(e){st.textContent='Error: '+e;document.getElementById('model').disabled=false;return;}var iv=setInterval(async function(){try{var r=await fetch('/api/switch-status');var j=await r.json();if(j.state==='loading'){st.textContent='Loading '+j.detail+'…';}else{clearInterval(iv);document.getElementById('model').disabled=false;st.textContent=(j.state==='ready'?'Model ready: ':'Switch failed: ')+j.detail;loadModels();}}catch(e){clearInterval(iv);document.getElementById('model').disabled=false;}},3000);}
async function query(){
  if(document.getElementById('go').disabled)return;
  const url=document.getElementById('url').value.trim()||'example.com';
  const year=document.getElementById('year').value||'1999';
  const btn=document.getElementById('go'),st=document.getElementById('status'),stopBtn=document.getElementById('stop');
  if(document.getElementById('model').disabled){st.textContent='Model still loading — wait…';return;}
  btn.disabled=true;stopBtn.disabled=false;ctrl=new AbortController();const t0=Date.now();let toks=0,html='';
  st.textContent='Contacting alternate '+year+'…';
  try{
    const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url,year:parseInt(year),context:hist.slice(-2).map(function(s){return{url:s.url,year:s.year,excerpt:textExcerpt(s.html)};})}),signal:ctrl.signal});
    if(!r.ok)throw new Error('HTTP '+r.status);
    const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){
      let read;
      try{read=await rd.read();}catch(e){if(e&&e.name==='AbortError')throw e;continue;}
      const{done,value}=read;if(done)break;
      try{buf+=dec.decode(value,{stream:true});}catch(e){continue;}
      const parts=buf.split('\\n\\n');buf=parts.pop();
      for(const p of parts){
        if(!p.startsWith('data:'))continue;
        const d=p.slice(5).trim();
        if(d==='[DONE]')continue;
        try{
          const j=JSON.parse(d);
          const t=j.choices?.[0]?.delta?.content||'';
          if(t){html+=t;toks++;st.textContent=`Receiving timeline… ${toks} tokens (${((Date.now()-t0)/1000).toFixed(0)}s)`;}
        }catch(e){}
      }
    }
    html=scrubDisclaimers(html);setSrc(html);
    hist=hist.slice(0,hi+1);hist.push({url:url,year:year,html:html});hi=hist.length-1;updNav();
    document.title=url+' ('+year+') — Alternate Universe Browser';
    st.textContent=`Rendered ${url} (${year}) — ${toks} tokens in ${((Date.now()-t0)/1000).toFixed(1)}s.`;
  }catch(e){
    if(e&&e.name==='AbortError'){
      html=scrubDisclaimers(html);setSrc(html);
      st.textContent=`Stopped — partial render (${toks} tokens).`;
    }else{st.textContent='Error: '+e;}
  }
  btn.disabled=false;stopBtn.disabled=true;ctrl=null;
}
</script></body></html>"""

app = Flask(__name__)


def build_messages(url: str, year: int, context: list | None = None) -> list:
    extra = ""
    u = url.lower()
    if "google" in u:
        if "search" in u:
            extra = (
                " This is a Google RESULTS page: Google logo header, large search box "
                "with the query filled in, 8 clickable blue result titles each with a "
                "green display URL and a 2-line snippet, a 'Related searches' row, and "
                "numbered pagination (1-5) at the bottom. Every result title, related "
                "search, and page number must be a real <a href> link so they can be "
                "clicked to continue browsing."
            )
        else:
            extra = (
                " This is the Google HOMEPAGE: huge multicolor GOOGLE logo centered, one "
                "large rounded search box, two buttons 'Google Search' and 'I am Feeling "
                "Lucky', minimal footer links (About, Privacy, Terms). An era-appropriate "
                "doodle above the logo is welcome. The Search button submits the form."
            )
    user_text = (
        f"URL: {url}\nYear: {year}\n"
        f"Render what {url} looked like (or will look like) in {year} "
        f"as a complete, era-authentic webpage.{extra}"
    )
    if context:
        trail = "\n".join(
            f"- {c.get('url', '?')} ({c.get('year', '?')}): {str(c.get('excerpt', ''))[:600]}"
            for c in context
            if isinstance(c, dict)
        )
        if trail:
            user_text += (
                "\nSession memory — pages just visited in this browser, most recent last:\n"
                f"{trail}\nStay consistent with them: same companies, product names, "
                "version numbers, and facts. The new page continues their story."
            )
    user_text += " Raw HTML only."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def strip_fences(html: str) -> str:
    """Defense in depth: remove markdown fences if the model adds them anyway."""
    m = re.search(r"```(?:html)?\s*(.*?)```", html, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else html.strip()


def clean_text(s: str) -> str:
    """Deterministic mojibake killer: the 4B ignores 'ASCII only', so enforce it.
    Fixes common double-encoded sequences, then drops any remaining non-ASCII
    (slop pages lose nothing of value). Safe on markup: no tag char is non-ASCII."""
    s = (
        s.replace("â€™", "'")
        .replace("â€œ", '"')
        .replace("â€¢", "-")
        .replace("â€", '"')
        .replace("â€“", "-")
        .replace("â€”", "-")
        .replace("Â©", "(c)")
        .replace("Â®", "(R)")
        .replace("Â", "")
        .replace("â", "")
    )
    return re.sub(r"[^\x09\x0a\x0d\x20-\x7e]", "", s)


def sanitize_event(event: str) -> str:
    """Clean model text inside one SSE event; pass everything else through."""
    if not event.startswith("data:"):
        return event
    payload = event[5:].strip()
    if payload == "[DONE]":
        return event
    try:
        obj = json.loads(payload)
    except ValueError:
        return event
    try:
        content = obj["choices"][0]["delta"]["content"]
    except (KeyError, IndexError, TypeError):
        return event
    if isinstance(content, str):
        obj["choices"][0]["delta"]["content"] = clean_text(content)
        return "data: " + json.dumps(obj, ensure_ascii=False)
    return event


@app.get("/")
def index():
    return PAGE


def _do_switch(model_id: str, ctx: int):
    _switch.update(state="loading", detail=model_id)
    try:
        prev = _current["id"]
        if prev != model_id:
            # exclusive loading: release the old model first so a big model
            # never shares 6 GB VRAM with the previous one (OOM risk)
            subprocess.run(["lemonade", "unpin", prev],
                           capture_output=True, text=True, timeout=60)
            subprocess.run(["lemonade", "unload", prev],
                           capture_output=True, text=True, timeout=300)
        r = subprocess.run(
            ["lemonade", "load", model_id, "--llamacpp", "cuda",
             "--ctx-size", str(ctx), "--llamacpp-args", LLAMACPP_ARGS,
             "--save-options"],
            capture_output=True, text=True, timeout=1200,
        )
        if r.returncode != 0:  # fall back to saved per-model options
            r = subprocess.run(["lemonade", "load", model_id],
                               capture_output=True, text=True, timeout=1200)
        if r.returncode == 0:
            _current["id"] = model_id
            _switch.update(state="ready", detail=model_id)
        else:
            err = (r.stderr or r.stdout or "unknown error")[-300:]
            _switch.update(state="error", detail=err)
    except Exception as e:  # noqa: BLE001 - report back, never crash the server
        _switch.update(state="error", detail=str(e)[-300:])


@app.get("/api/models")
def list_models():
    try:
        r = requests.get(f"{LEMONADE_BASE}/models", timeout=15)
        data = r.json().get("data", [])
        ids = [m["id"] for m in data
               if m.get("id") and ("downloaded" not in m or m.get("downloaded"))]
    except Exception:  # noqa: BLE001 - Lemonade unreachable, offer current only
        ids = []
    if _current["id"] not in ids:
        ids = [_current["id"]] + ids
    return {"models": ids, "current": _current["id"]}


@app.post("/api/switch")
def switch_model():
    if _switch["state"] == "loading":
        return {"status": "busy"}, 409
    data = request.get_json(force=True)
    model_id = str(data.get("model", ""))[:120]
    if not model_id:
        return {"status": "missing model"}, 400
    if model_id == _current["id"]:
        return {"status": "already", "model": model_id}
    ctx = MODEL_PRESETS.get(model_id, {}).get("ctx", 4096)
    threading.Thread(target=_do_switch, args=(model_id, ctx), daemon=True).start()
    return {"status": "loading", "model": model_id}, 202


@app.get("/api/switch-status")
def switch_status():
    return {"state": _switch["state"], "detail": _switch.get("detail", ""),
            "current": _current["id"]}


@app.post("/api/query")
def query():
    data = request.get_json(force=True)
    url = str(data.get("url", "example.com"))[:200]
    try:
        year = int(data.get("year", 1999))
    except (TypeError, ValueError):
        year = 1999
    context = data.get("context") or []

    upstream = requests.post(
        f"{LEMONADE_BASE}/chat/completions",
        json={
            "model": _current["id"],
            "messages": build_messages(url, year, context),
            "max_tokens": MAX_TOKENS,
            "temperature": 0.6,
            "stream": True,
        },
        stream=True,
        timeout=TIMEOUT,
    )

    def generate():
        buf = ""
        try:
            for chunk in upstream.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
                    buf += chunk
                    while "\n\n" in buf:
                        event, buf = buf.split("\n\n", 1)
                        yield sanitize_event(event) + "\n\n"
        finally:
            upstream.close()  # frees the model slot when the client stops early
        # Note: fence-stripping happens client-side on completion is skipped
        # for streaming; the prompt forbids fences and strip_fences() covers
        # non-streaming callers reusing build_messages().

    return Response(
        stream_with_context(generate()), mimetype="text/event-stream"
    )


@app.post("/api/render")
def render_once():
    """Non-streaming variant (simpler clients). Returns {"html": ...}."""
    data = request.get_json(force=True)
    url = str(data.get("url", "example.com"))[:200]
    try:
        year = int(data.get("year", 1999))
    except (TypeError, ValueError):
        year = 1999
    context = data.get("context") or []
    r = requests.post(
        f"{LEMONADE_BASE}/chat/completions",
        json={
            "model": _current["id"],
            "messages": build_messages(url, year, context),
            "max_tokens": MAX_TOKENS,
            "temperature": 0.6,
        },
        timeout=TIMEOUT,
    )
    content = r.json()["choices"][0]["message"]["content"]
    return {"html": clean_text(strip_fences(content))}


if __name__ == "__main__":
    print(f"Model: {MODEL} via {LEMONADE_BASE} @ ~34 tok/s")
    app.run(host="127.0.0.1", port=5057, threaded=True)
