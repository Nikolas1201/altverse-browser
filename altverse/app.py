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
import tempfile
import threading
import time

import requests
from flask import Flask, Response, request, stream_with_context

LEMONADE_BASE = "http://127.0.0.1:13305/v1"
MODEL = os.environ.get("ALTVERSE_MODEL", "Qwen3-4B-Instruct-2507-GGUF")


def detect_backend() -> str:
    """NVIDIA present -> cuda, anything else -> vulkan."""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                           text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return "cuda"
    except Exception:  # noqa: BLE001 - no NVIDIA driver, fall through
        pass
    return "vulkan"


BACKEND = os.environ.get("ALTVERSE_BACKEND", detect_backend())
MAX_TOKENS = 3600
TIMEOUT = 600

LLAMACPP_ARGS = "--flash-attn on --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 --threads 5 --threads-batch 5"
MODEL_PRESETS = {
    "Qwen3-4B-Instruct-2507-GGUF": {"ctx": 4096, "temp": 0.6, "max": 3600},
    "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M": {"ctx": 8192, "temp": 0.7, "max": 3600},
    "Qwen3-0.6B-GGUF": {"ctx": 2048, "temp": 0.2, "max": 700, "simple": True},
}
DEFAULT_TEMP, DEFAULT_MAX = 0.6, 3600
_current = {"id": MODEL}
_switch = {"state": "idle", "detail": ""}


def _gen_params(model_id: str, data: dict) -> tuple:
    """Per-model generation tuning: preset temp/cap, overridable per request."""
    preset = MODEL_PRESETS.get(model_id, {})
    try:
        temp = float(data.get("temp", preset.get("temp", DEFAULT_TEMP)))
    except (TypeError, ValueError):
        temp = preset.get("temp", DEFAULT_TEMP)
    temp = max(0.0, min(2.0, temp))
    max_tok = min(int(preset.get("max", DEFAULT_MAX)), MAX_TOKENS)
    return temp, max_tok, bool(preset.get("simple", False))  # 4B @ ~34 tok/s finishes a page in well under this

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
body{background:#f0f0f4;color:#15141a;font-family:system-ui,"Segoe UI",Arial,sans-serif;margin:0}
#tabstrip{display:flex;align-items:flex-end;gap:2px;padding:8px 10px 0;background:#dcd9e2}
.tab{background:transparent;border-radius:10px 10px 0 0;padding:8px 12px;font-size:13px;display:flex;gap:10px;align-items:center;max-width:300px;white-space:nowrap;overflow:hidden;cursor:pointer;color:#4a4a55}
.tab:not(.active){border-left:1px solid #c0bec8}
.tab:not(.active):hover{background:#d2cfd9}
.tab.active{background:#ffffff;border:1px solid #cfcfd8;border-bottom:0;color:#15141a}
.tablabel{overflow:hidden;text-overflow:ellipsis}
.tabx{cursor:pointer;color:#6d6d80;border-radius:4px;padding:0 4px;flex:none}
.tabx:hover{background:#d8d6e0}
#newtab{cursor:pointer;color:#4a4a55;font-size:18px;padding:2px 8px;border-radius:6px}
#newtab:hover{background:#d8d6e0}
@keyframes tabIn{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:none}}
.tab.fresh{animation:tabIn .22s ease-out}
.tab .dot{animation:pulse 1.1s ease-in-out infinite;color:#0060df;font-weight:bold;margin-left:2px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.tablabel{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
#toolbar{display:flex;gap:2px;padding:8px 10px;background:#ffffff;align-items:center}
button{background:transparent;border:0;color:#15141a;font-size:16px;padding:7px 9px;border-radius:7px;cursor:pointer}
button:hover:not(:disabled){background:#dcdce4}
button:disabled{opacity:.35;cursor:default}
#url{flex:1;border-radius:20px;background:#fff;border:1px solid #cfcfd8;padding:9px 16px;font-size:14px;color:#15141a;min-width:120px}
#year{width:78px;border-radius:20px;background:#fff;border:1px solid #cfcfd8;padding:9px 10px;font-size:14px;color:#15141a}
#aibar{display:flex;gap:10px;padding:7px 12px;background:#e8e7ee;border-top:1px solid #d5d3dd;align-items:center;font-size:13px;color:#3a3a44}
#go{background:#0060df;border-color:#0060df;color:#fff;font-weight:600;font-size:14px;padding:8px 16px;border-radius:8px}
#stop{background:#d70022;border-color:#d70022;color:#fff;font-weight:600;font-size:14px;padding:8px 14px;border-radius:8px}
#model{background:#fff;border:1px solid #cfcfd8;border-radius:8px;padding:7px;font-size:13px;color:#15141a;max-width:230px}
#aibar label{display:flex;gap:5px;align-items:center}
#temp{width:90px;vertical-align:middle;accent-color:#0060df}
#tempv{min-width:28px}
#status{padding:6px 14px;color:#5b5b66;font-size:12px;min-height:18px;background:#f0f0f4}
iframe{width:100%;height:calc(100vh - 196px);border:0;background:#fff;display:block}
</style></head><body>
<div id="tabstrip"><div id="tab"><span id="tabtitle">New Timeline</span><span id="tabx" onclick="goHome()" title="New timeline">×</span></div><div id="newtab" onclick="goHome()" title="New timeline">+</div></div>
<div id="toolbar">
<button id="back" onclick="goBack()" disabled title="Back">&larr;</button>
<button id="fwd" onclick="goFwd()" disabled title="Forward">&rarr;</button>
<button id="rel" onclick="query()" title="Reload timeline">&#8635;</button>
<button id="home" onclick="goHome()" title="Home">⌂</button>
<input id="url" value="youtube.com" placeholder="example.com">
<input id="year" type="number" value="1999" min="1960" max="2100">
</div>
<div id="aibar">
<button id="go" onclick="query()">Query Reality</button>
<button id="stop" onclick="stopGen()" disabled>Stop</button>
<select id="model" onchange="switchModel()" title="AI model"></select>
<button id="hfbtn" onclick="openHf()" title="Add model from HuggingFace">+</button>
<label title="Session memory: send last pages as context"><input type="checkbox" id="usemem" checked style="width:auto">Mem</label>
<input type="range" id="temp" min="0" max="1.2" step="0.1" value="0.6" title="Temperature: lower = obedient, higher = unhinged" oninput="document.getElementById('tempv').textContent=this.value"><span id="tempv" title="Temperature">0.6</span>
</div>
<div id="hfmodal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.45);z-index:50">
<div style="background:#f0f0f4;color:#15141a;max-width:640px;margin:8vh auto;padding:18px;border-radius:14px;max-height:80vh;overflow:auto">
<div style="display:flex;gap:8px"><input id="hfq" placeholder="Search HuggingFace GGUFs..." style="flex:1;background:#fff;border:1px solid #cfcfd8;border-radius:8px;padding:8px 12px;font-size:14px;color:#15141a" onkeydown="if(event.key==='Enter')hfSearch()"><button id="hfgo" onclick="hfSearch()" style="background:#0060df;color:#fff;border-radius:8px;padding:8px 14px;font-size:14px">Search</button><button onclick="closeHf()" title="Close" style="background:#d8d6e0;border-radius:8px;padding:8px 12px;font-size:14px">X</button></div>
<div id="hfres" style="margin-top:12px;font-size:14px"></div>
</div></div>
<div id="status">Enter a URL and a year, then Query Reality.</div>
<iframe id="view" sandbox="allow-scripts" srcdoc="<body style='background:#fff;color:#888;font-family:sans-serif'><p style='padding:40px'>The void awaits your query&hellip;</p>"></iframe>
<script>
let ctrl=null;
function stopGen(){
  var t=activeTab();if(!t)return;
  if(t.ctrl){try{t.ctrl.abort();}catch(e){}}
  else if(t.queued){t.queued=false;genQueue=genQueue.filter(function(x){return x!==t.id;});t.status='Stopped before starting.';paintAll();}
}
function requestGen(t){
  if(!t||t.dead)return;
  if(t.ctrl||t.queued)return;
  t.toks=0;t.html='';
  if(genLock===null&&genQueue.length===0)startGen(t);
  else{t.queued=true;genQueue.push(t.id);t.status='Waiting for other tab to finish…';paintAll();}
}
function pumpQueue(){
  while(genLock===null&&genQueue.length){
    var id=genQueue.shift(),t=null;
    for(var i=0;i<tabs.length;i++)if(tabs[i].id===id)t=tabs[i];
    if(!t||t.dead||!t.queued)continue;
    startGen(t);return;
  }
  paintAll();
}
function startGen(t){
  genLock=t.id;t.queued=false;t.started=true;t.gen=(t.gen||0)+1;
  var myGen=t.gen,url=t.url,year=t.year;
  t.ctrl=new AbortController();t.t0=Date.now();t.toks=0;t.html='';
  t.status='Contacting alternate '+year+'…';paintAll();
  (async function(){
    var html='',toks=0,outcome=null;
    var stEl=document.getElementById('status');
    try{
      const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url:url,year:parseInt(year),temp:parseFloat(document.getElementById('temp').value),context:document.getElementById('usemem').checked?t.hist.slice(-2).map(function(s){return{url:s.url,year:s.year,excerpt:textExcerpt(s.html)};}):[]}),signal:t.ctrl.signal});
      if(t.gen!==myGen||t.dead)return;
      if(!r.ok)throw new Error('HTTP '+r.status);
      const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
      while(true){
        let read;
        try{read=await rd.read();}catch(e){if(e&&e.name==='AbortError')throw e;continue;}
        if(t.gen!==myGen||t.dead)return;
        const{done,value}=read;if(done)break;
        try{buf+=dec.decode(value,{stream:true});}catch(e){continue;}
        const parts=buf.split('\\n\\n');buf=parts.pop();
        for(const p of parts){
          if(!p.startsWith('data:'))continue;
          const d=p.slice(5).trim();
          if(d==='[DONE]')continue;
          try{
            const j=JSON.parse(d);
            const tt=j.choices?.[0]?.delta?.content||'';
            if(tt){html+=tt;toks++;t.toks=toks;t.status=`Receiving timeline… ${toks} tokens`;if(t.id===activeId&&t.gen===myGen)stEl.textContent=t.status+` (${((Date.now()-t.t0)/1000).toFixed(0)}s)`;}
          }catch(e){}
        }
      }
      if(t.gen!==myGen||t.dead)return;
      html=scrubDisclaimers(html);t.html=html;
      t.hist=t.hist.slice(0,t.hi+1);t.hist.push({url:url,year:year,html:html});t.hi=t.hist.length-1;
      t.status=`Rendered ${url} (${year}) — ${toks} tokens in ${((Date.now()-t.t0)/1000).toFixed(1)}s.`;
      outcome='done';
    }catch(e){
      if(t.gen!==myGen||t.dead)return;
      if(e&&e.name==='AbortError'){t.html=scrubDisclaimers(html);t.status=`Stopped — partial render (${toks} tokens).`;outcome='stopped';}
      else{t.status='Error: '+e;outcome='error';}
    }finally{
      var mine=(t.gen===myGen);
      if(t.dead){var ix=tabs.indexOf(t);if(ix>=0)tabs.splice(ix,1);}
      if(mine&&genLock===t.id)genLock=null;
      if(mine){t.ctrl=null;t.started=false;t.queued=false;}
      if(outcome&&(t.id===activeId)&&!t.dead){setSrc(t.html);document.title=url+' ('+year+') — Alternate Universe Browser';}
      renderTabs();paintAll();pumpQueue();
    }
  })();
}
function ensureCharset(h){if(/<meta[^>]*charset/i.test(h))return h;var m=h.match(/<head[^>]*>/i);if(m)return h.replace(m[0],m[0]+'<meta charset="utf-8">');return '<meta charset="utf-8">'+h;}
var HOOK='<script>(function(){function q(f){var i=f.querySelector("input[type=text],input[type=search],input:not([type])");return i?i.value:"";}function nq(el){var c=el.parentElement;for(var i=0;i<5&&c;i++){var inp=c.querySelector("input[type=text],input[type=search],input:not([type])");if(inp)return inp.value;c=c.parentElement;}var g=document.querySelector("input[type=text],input[type=search],input:not([type])");return g?g.value:"";}document.addEventListener("submit",function(e){e.preventDefault();parent.postMessage({t:"altverse-search",q:q(e.target)},"*");},true);document.addEventListener("click",function(e){var b=e.target.closest("button,input[type=submit],input[type=button]");if(b){e.preventDefault();var f=b.closest("form");parent.postMessage({t:"altverse-search",q:f?q(f):nq(b)},"*");return;}var a=e.target.closest("a");if(a&&a.getAttribute("href")){e.preventDefault();parent.postMessage({t:"altverse-nav",url:a.getAttribute("href")},"*");}},true);})();<\/script>';
function setSrc(h){h=ensureCharset(h);if(/<\/body\s*>/i.test(h))h=h.replace(/<\/body\s*>/i,HOOK+'</body>');else h+=HOOK;document.getElementById('view').srcdoc=h;}
function textExcerpt(h){var t=h.replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ').replace(/<[^>]+>/g,' ');return t.replace(/\s+/g,' ').trim().slice(0,600);}
function scrubDisclaimers(h){return h.replace(/[^<>]*(?:fan fiction|satire|no actual shoes|fictional|fake entry|do not buy|do not seek|not affiliated|entertainment purposes only|important note\s*:)[^.]*\./gi,'');}
window.addEventListener('message',function(e){var d=e.data||{};var t=activeTab();if(!t)return;var tu=(t.url||'').trim();var u=tu||'example.com';if(tu===''||tu==='home'){u='google.com';}if(d.t==='altverse-search'){if(d.q){u=u+'/search?q='+encodeURIComponent(d.q);}document.getElementById('url').value=u;query();}if(d.t==='altverse-nav'){document.getElementById('url').value=d.url;query();}});
let tabs=[],activeId=0,nextId=1,genLock=null,genQueue=[];
var freshTabs={},lastStripSig='';
var HOMEHTML='<!DOCTYPE html><html><head><meta charset="utf-8"><title>New Timeline</title><style>body{margin:0;background:#f4f2fa;font-family:system-ui,Segoe UI,Arial,sans-serif;color:#15141a}main{max-width:620px;margin:11vh auto 0;text-align:center;padding:0 20px}h1{font-size:46px;margin:0 0 4px;font-weight:800}h1 .a{color:#0060df}p.sub{color:#5b5b66;margin:0 0 26px;font-size:15px}form{display:flex;gap:8px;justify-content:center}input[type=text]{flex:1;max-width:400px;padding:12px 18px;font-size:15px;border-radius:24px;border:1px solid #cfcfd8}button{padding:12px 22px;font-size:15px;border-radius:24px;border:0;background:#0060df;color:#fff;cursor:pointer}.tiles{display:flex;gap:10px;justify-content:center;margin-top:32px;flex-wrap:wrap}.tiles a{display:block;width:148px;padding:14px 8px;background:#fff;border:1px solid #e2e0e8;border-radius:12px;text-decoration:none;color:#15141a;font-size:13px}.tiles a b{display:block;font-size:14px;margin-bottom:4px}.tiles a span{color:#5b5b66;font-size:12px}</style></head><body><main><h1><span class="a">A</span>ltVerse</h1><p class="sub">Every timeline ever. None of it true.</p><form method="get" action="#"><input type="text" name="q" placeholder="Search the multiverse..."><button type="submit">Search</button></form><div class="tiles"><a href="youtube.com"><b>YouTube</b><span>Static &amp; loud</span></a><a href="myspace.com"><b>MySpace</b><span>Top 8 included</span></a><a href="google.com"><b>Google</b><span>Do the obvious</span></a></div></main></body></html>';
function homeState(t){t.url='';t.year=new Date().getFullYear();t.hist=[{url:'home',year:'',html:HOMEHTML}];t.hi=0;t.html=HOMEHTML;t.toks=0;t.started=false;t.queued=false;t.ctrl=null;t.status='';t.dead=false;}
var VOIDSRC="<body style='background:#fff;color:#888;font-family:sans-serif'><p style='padding:40px'>The void awaits your query&hellip;</p>";
function activeTab(){for(var i=0;i<tabs.length;i++)if(tabs[i].id===activeId)return tabs[i];return null;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function renderTabs(){var sig=tabs.map(function(t){return t.id+':'+(t.id===activeId)+':'+(t.started||t.queued)+':'+t.url;}).join('|');if(sig===lastStripSig)return;lastStripSig=sig;var h='';tabs.forEach(function(t){var cls='tab'+(t.id===activeId?' active':'');if(freshTabs[t.id]){cls+=' fresh';delete freshTabs[t.id];}var dot=(t.started||t.queued)?'<span class="dot">\u2022</span>':'';h+='<div class="'+cls+'" onclick="activateTab('+t.id+')"><span class="tablabel">'+esc(t.url||'New Timeline')+'</span>'+dot+'<span class="tabx" onclick="event.stopPropagation();closeTab('+t.id+')" title="Close tab">\u00d7</span></div>';});h+='<div id="newtab" onclick="newTab()" title="New timeline">+</div>';document.getElementById('tabstrip').innerHTML=h;}
function paintAll(){
  renderTabs();
  var t=activeTab();if(!t)return;
  var st=document.getElementById('status');
  if(t.started)st.textContent=t.status;
  else if(t.queued)st.textContent='Waiting for other tab to finish…';
  else st.textContent=t.status||'Enter a URL and a year, then Query Reality.';
  document.getElementById('stop').disabled=!(t.started||t.queued);
  document.getElementById('back').disabled=!(t.hi>0);
  document.getElementById('fwd').disabled=!(t.hi<t.hist.length-1);
}
function activateTab(id){
  var t=null;for(var i=0;i<tabs.length;i++)if(tabs[i].id===id)t=tabs[i];
  if(!t||t.dead)return;
  activeId=id;
  document.getElementById('url').value=t.url;
  document.getElementById('year').value=t.year;
  if(t.html)setSrc(t.html);
  else document.getElementById('view').srcdoc=VOIDSRC;
  document.title=t.url?(t.url+' ('+t.year+') - Alternate Universe Browser'):'Alternate Universe Browser';
  paintAll();
}
function newTab(){var t={id:nextId++,gen:0};homeState(t);tabs.push(t);freshTabs[t.id]=1;activateTab(t.id);return t;}
function closeTab(id){
  var i=-1;for(var k=0;k<tabs.length;k++)if(tabs[k].id===id)i=k;
  if(i<0)return;
  var t=tabs[i];t.dead=true;
  genQueue=genQueue.filter(function(x){return x!==id;});
  if(t.ctrl){try{t.ctrl.abort();}catch(e){}}
  if(genLock===id)genLock=null;
  tabs.splice(i,1);
  if(activeId===id){
    if(tabs.length)activateTab(tabs[Math.min(i,tabs.length-1)].id);
    else newTab();
  }else{renderTabs();}
  pumpQueue();
}
function restore(){var t=activeTab();if(!t||t.hi<0||t.hi>=t.hist.length)return;var s=t.hist[t.hi];document.getElementById('url').value=s.url;document.getElementById('year').value=s.year;t.url=s.url;t.year=s.year;setSrc(s.html);document.title=s.url+' ('+s.year+') — Alternate Universe Browser';paintAll();}
function goBack(){var t=activeTab();if(t&&t.hi>0){t.hi--;restore();}}
function goFwd(){var t=activeTab();if(t&&t.hi<t.hist.length-1){t.hi++;restore();}}
function goHome(){var t=activeTab();if(!t)return;if(t.ctrl){try{t.ctrl.abort();}catch(e){}t.ctrl=null;t.started=false;t.queued=false;t.gen=(t.gen||0)+1;if(genLock===t.id)genLock=null;}genQueue=genQueue.filter(function(x){return x!==t.id;});homeState(t);activateTab(t.id);pumpQueue();}
window.addEventListener('load',function(){loadModels();newTab();});
async function loadModels(){try{var r=await fetch('/api/models');var j=await r.json();window.mdefs=j.defaults||{};var s=document.getElementById('model');s.innerHTML='';j.models.forEach(function(m){var o=document.createElement('option');o.value=m;o.textContent=m.length>30?m.slice(0,30)+'…':m;if(m===j.current)o.selected=true;s.appendChild(o);});var d=window.mdefs[j.current];if(d&&d.temp!==undefined){document.getElementById('temp').value=d.temp;document.getElementById('tempv').textContent=d.temp;}}catch(e){}}
async function switchModel(){var m=document.getElementById('model').value;var st=document.getElementById('status');document.getElementById('model').disabled=true;st.textContent='Loading '+m+' — minutes for big models…';try{await fetch('/api/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:m})});}catch(e){st.textContent='Error: '+e;document.getElementById('model').disabled=false;return;}var iv=setInterval(async function(){try{var r=await fetch('/api/switch-status');var j=await r.json();if(j.state==='loading'){st.textContent='Loading '+j.detail+'…';}else{clearInterval(iv);document.getElementById('model').disabled=false;st.textContent=(j.state==='ready'?'Model ready: ':'Switch failed: ')+j.detail;loadModels();}}catch(e){clearInterval(iv);document.getElementById('model').disabled=false;}},3000);}
function openHf(){document.getElementById('hfmodal').style.display='block';document.getElementById('hfq').focus();window._hfFlat=[];}
function closeHf(){document.getElementById('hfmodal').style.display='none';}document.getElementById('hfres').addEventListener('click',function(e){var g=e.target.closest('button[data-hfgo]');if(g){hfFiles(+g.getAttribute('data-hfgo'));return;}var b=e.target.closest('button[data-hfimp]');if(b){var o=window._hfFlat[+b.getAttribute('data-hfimp')];if(o)hfImport(o.r,o.f,o.g,o.i);}});
async function hfSearch(){
  var q=document.getElementById('hfq').value.trim();
  var box=document.getElementById('hfres');
  if(q.length<2){box.textContent='Type at least 2 characters.';return;}
  box.textContent='Searching...';
  try{
    var r=await fetch('/api/hf-search?q='+encodeURIComponent(q));
    var j=await r.json();
    if(!j.results||!j.results.length){box.textContent='No GGUF models found.';return;}
    window._hfRepos=j.results.map(function(m){return m.id;});
    var h='';
    j.results.forEach(function(m,i){
      h+='<div style="padding:8px 0;border-bottom:1px solid #ddd"><b>'+esc(m.id)+'</b><br><span style="color:#666">'+m.downloads+' downloads</span> <button style="background:#0060df;color:#fff;border-radius:6px;padding:4px 10px;font-size:13px" data-hfgo="'+i+'"</button><div id="hffiles'+i+'"></div></div>';
    });
    box.innerHTML=h;
  }catch(e){box.textContent='Error: '+e;}
}
async function hfFiles(i){
  var repo=window._hfRepos[i];
  var div=document.getElementById('hffiles'+i);
  div.textContent='Loading files...';
  try{
    var r=await fetch('/api/hf-files?repo='+encodeURIComponent(repo));
    var j=await r.json();
    if(!j.files||!j.files.length){div.textContent='No GGUF files in this repo.';return;}
    var h='';
    j.files.forEach(function(f){
      h+='<div style="padding:3px 0 3px 12px">'+esc(f.file)+' <span style="color:#666">'+f.gb+' GB</span> <button style="background:#238636;color:#fff;border-radius:6px;padding:3px 10px;font-size:13px" data-hfimp="'+(window._hfFlat.push({r:repo,f:f.file,g:f.gb,i:i})-1)+'"</button></div>';
    });
    div.innerHTML=h+'<div id="hfstatus'+i+'" style="color:#666"></div>';
  }catch(e){div.textContent='Error: '+e;}
}
async function hfImport(i,file,gb){
  var repo=window._hfRepos[i];
  var st=document.getElementById('hfstatus'+i);
  st.textContent='Importing...';
  try{
    var r=await fetch('/api/hf-import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo:repo,file:file,gb:gb})});
    var j=await r.json();
    if(j.status==='imported'){st.textContent='Imported as '+j.model+'. Weights download on first use. Pick it from the model menu.';loadModels();}
    else{st.textContent='Failed: '+(j.detail||j.status);}
  }catch(e){st.textContent='Error: '+e;}
}
async function query(){
  if(document.getElementById('go').disabled)return;
  var t=activeTab();if(!t)return;
  if(document.getElementById('model').disabled){document.getElementById('status').textContent='Model still loading - wait...';return;}
  t.url=document.getElementById('url').value.trim()||'example.com';
  t.year=document.getElementById('year').value||'1999';
  renderTabs();
  if(t.ctrl){try{t.ctrl.abort();}catch(e){}t.ctrl=null;t.started=false;t.queued=false;t.gen=(t.gen||0)+1;if(genLock===t.id)genLock=null;}
  genQueue=genQueue.filter(function(x){return x!==t.id;});
  requestGen(t);
  pumpQueue();
}
</script></body></html>"""

app = Flask(__name__)


def build_messages(url: str, year: int, context: list | None = None,
                   simple: bool = False) -> list:
    extra = ""
    u = url.lower()
    # Descriptive page briefs read as page CONTENT to weak models (they print
    # the directions), so simple mode gets the skeleton only.
    if "google" in u and not simple:
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
    if "youtube" in u:
        if "watch" in u or "v=" in u:
            extra += (
                " Build a YouTube WATCH page: big black video player rectangle, "
                "bold video title below it, Like Dislike Share buttons, "
                "3 viewer comments with usernames."
            )
        else:
            extra += (
                " Build a YouTube HOMEPAGE: red YOUTUBE logo top-left, one search box, "
                "a grid of 6 video boxes. Each box: colored thumbnail rectangle, "
                "bold title line, gray view-count line. Sidebar links: "
                "Home, Shorts, Subscriptions."
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
    if simple:
        user_text += (
            " Small model mode: follow this exact skeleton in order and stop: "
            "1) centered site-name headline, 2) a search form, "
            "3) at least 3 blue <a href> links each with a one-line description."
        )
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


def _loaded_ids() -> list:
    try:
        r = subprocess.run(["lemonade", "status", "--json"],
                           capture_output=True, text=True, timeout=30)
        return [m.get("model_name") for m in
                json.loads(r.stdout).get("models", [])]
    except Exception:  # noqa: BLE001 - fall through to load path
        return []


def _do_switch(model_id: str, ctx: int):
    _switch.update(state="loading", detail=model_id)
    try:
        if model_id in _loaded_ids():
            # already resident: flip instantly, no unload/reload cycle
            _current["id"] = model_id
            _switch.update(state="ready", detail=model_id)
            return
        prev = _current["id"]
        if prev != model_id:
            # exclusive loading: release the old model first so a big model
            # never shares 6 GB VRAM with the previous one (OOM risk)
            subprocess.run(["lemonade", "unpin", prev],
                           capture_output=True, text=True, timeout=60)
            subprocess.run(["lemonade", "unload", prev],
                           capture_output=True, text=True, timeout=300)
        r = subprocess.run(
            ["lemonade", "load", model_id, "--llamacpp", BACKEND,
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
    defaults = {mid: {"temp": MODEL_PRESETS.get(mid, {}).get("temp", DEFAULT_TEMP),
                      "max": min(int(MODEL_PRESETS.get(mid, {}).get("max", DEFAULT_MAX)), MAX_TOKENS)}
                for mid in ids}
    return {"models": ids, "current": _current["id"], "defaults": defaults}


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


HF_API = "https://huggingface.co/api"
HF_UA = {"User-Agent": "altverse-browser/1.0"}


@app.get("/api/hf-search")
def hf_search():
    q = str(request.args.get("q", ""))[:120].strip()
    if len(q) < 2:
        return {"results": []}
    try:
        r = requests.get(f"{HF_API}/models",
                         params={"search": q, "filter": "gguf",
                                 "sort": "downloads", "direction": -1,
                                 "limit": 20},
                         headers=HF_UA, timeout=20)
        out = [{"id": m.get("id", ""), "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0)}
               for m in r.json() if m.get("id")]
    except Exception:  # noqa: BLE001 - offline or HF hiccup, empty list
        out = []
    return {"results": out}


@app.get("/api/hf-files")
def hf_files():
    repo = str(request.args.get("repo", ""))[:200].strip()
    if "/" not in repo:
        return {"files": []}
    try:
        r = requests.get(f"{HF_API}/models/{repo}/tree/main",
                         params={"recursive": "True"}, headers=HF_UA,
                         timeout=20)
        files = [{"file": e.get("path", ""),
                  "gb": round((e.get("size") or 0) / 1e9, 2)}
                 for e in r.json()
                 if isinstance(e, dict)
                 and e.get("type") != "directory"
                 and str(e.get("path", "")).lower().endswith(".gguf")]
        files.sort(key=lambda e: e["gb"])
    except Exception:  # noqa: BLE001 - offline or bad repo, empty list
        files = []
    return {"files": files}


def _safe_model_name(repo: str, filename: str) -> str:
    base = repo.split("/")[-1].strip() or "custom"
    quant = filename.rsplit(".", 1)[0].split("-")[-1]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{base}-{quant}").strip(".-")[:80]
    return f"user.{name or 'custom'}"


@app.post("/api/hf-import")
def hf_import():
    data = request.get_json(force=True)
    repo = str(data.get("repo", ""))[:200].strip()
    filename = str(data.get("file", ""))[:200].strip()
    if "/" not in repo or not filename.lower().endswith(".gguf") or "/" in filename:
        return {"status": "bad request"}, 400
    name = _safe_model_name(repo, filename)
    spec = {
        "checkpoints": {"main": f"{repo}:{filename}"},
        "labels": ["chat"],
        "model_name": name,
        "recipe": "llamacpp",
        "recipe_options": {
            "ctx_size": 4096,
            "llamacpp_args": LLAMACPP_ARGS,
            "llamacpp_backend": BACKEND,
        },
        "registry_source": "huggingface",
        "size": float(data.get("gb", 0) or 0),
        "source": "huggingface",
    }
    try:
        spec_path = os.path.join(tempfile.gettempdir(), "altverse-import.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        r = subprocess.run(["lemonade", "import", spec_path],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return {"status": "import failed",
                    "detail": (r.stderr or r.stdout or "")[-500:]}, 500
    except Exception as e:  # noqa: BLE001 - report back, never crash
        return {"status": "error", "detail": str(e)[-300:]}, 500
    return {"status": "imported", "model": name}


@app.post("/api/query")
def query():
    data = request.get_json(force=True)
    url = str(data.get("url", "example.com"))[:200]
    try:
        year = int(data.get("year", 1999))
    except (TypeError, ValueError):
        year = 1999
    context = data.get("context") or []
    temp, max_tok, simple = _gen_params(_current["id"], data)

    upstream = requests.post(
        f"{LEMONADE_BASE}/chat/completions",
        json={
            "model": _current["id"],
            "messages": build_messages(url, year, context, simple),
            "max_tokens": max_tok,
            "temperature": temp,
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
    temp, max_tok, simple = _gen_params(_current["id"], data)
    r = requests.post(
        f"{LEMONADE_BASE}/chat/completions",
        json={
            "model": _current["id"],
            "messages": build_messages(url, year, context, simple),
            "max_tokens": max_tok,
            "temperature": temp,
        },
        timeout=TIMEOUT,
    )
    content = r.json()["choices"][0]["message"]["content"]
    return {"html": clean_text(strip_fences(content))}


if __name__ == "__main__":
    print(f"Model: {MODEL} via {LEMONADE_BASE} @ backend={BACKEND}")
    app.run(host="127.0.0.1", port=5057, threaded=True)
