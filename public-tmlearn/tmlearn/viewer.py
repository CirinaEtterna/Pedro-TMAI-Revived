"""Local web viewer of a training run: what the AI sees, its decisions, learning curves, live parameters.

Served by the learner process on http://127.0.0.1:<port>. The collector sends step payloads and JPEG
frames through `training.viewer_queue`; parameters are edited through `training.params`.
"""

__all__ = ['Viewer']

import asyncio
import json
import logging
import math
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .net import ThreadServer
from .params import SCHEMA

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PedroAI</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root{--bg:#121417;--panel:#1c2026;--line:#2b313a;--text:#e6e9ef;--muted:#8a94a6;--accent:#4fc3f7;--good:#66bb6a;--bad:#ef5350;--warn:#ffb74d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 system-ui,Segoe UI,Roboto,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header h1{font-size:16px;margin:0}header .tribute{color:var(--muted);font-size:12px;margin-right:12px}header .pill{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px 10px;color:var(--muted)}
header .pill b{color:var(--text)}#status.off{color:var(--bad)}
main{display:grid;grid-template-columns:minmax(320px,1fr) minmax(320px,1fr);gap:12px;padding:12px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.card h2{font-size:13px;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
#frame{width:100%;aspect-ratio:16/9;background:#000;border-radius:6px;display:block;object-fit:contain}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-top:10px}
.stat{background:var(--bg);border-radius:8px;padding:8px}.stat .v{font-size:20px;font-weight:600}.stat .l{color:var(--muted);font-size:11px}
.bar{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px}.bar .n{width:48px;color:var(--muted);font-family:ui-monospace,monospace}
.bar .t{flex:1;height:10px;background:var(--bg);border-radius:5px;overflow:hidden}.bar .f{height:100%;background:var(--accent)}
.bar.sel .f{background:var(--good)}.bar.user .n{color:var(--warn)}
.params .row{display:grid;grid-template-columns:1fr 150px;gap:8px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}
.params .row:first-of-type{border-top:0}.params label{display:block}.params small{display:block;color:var(--muted)}
.params input[type=number],.params select{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:5px}
.params .group{margin-top:10px;color:var(--accent);font-size:12px;font-weight:600}
button{background:var(--accent);color:#000;border:0;border-radius:6px;padding:8px 14px;font-weight:600;cursor:pointer}button:disabled{opacity:.5}
.master{display:flex;align-items:center;gap:10px;padding:8px;border-radius:8px;background:var(--bg);margin-bottom:8px}
.master.on{outline:2px solid var(--warn)}.master input{width:20px;height:20px}
canvas{max-height:220px}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:3px 6px;text-align:right;border-top:1px solid var(--line)}th{color:var(--muted)}td:first-child,th:first-child{text-align:left}
#msg{color:var(--muted);font-size:12px;margin-left:8px}
</style></head><body>
<header><h1>PedroAI</h1><span class="tribute" title="Pedro's work picked up again on October 15, 2026, one month before his birthday (November 15)">continuing Pedro's work since October 15, 2026</span>
<span class="pill">run <b id="run">-</b></span><span class="pill">env <b id="envname">-</b></span>
<span class="pill">learner <b id="learner">-</b></span><span class="pill">buffer <b id="buffer">-</b></span>
<span class="pill" id="status">connecting…</span></header>
<main>
<section class="card"><h2>What the AI sees</h2><img id="frame" alt="game frame">
<div class="stats">
<div class="stat"><div class="v" id="speed">-</div><div class="l">km/h</div></div>
<div class="stat"><div class="v" id="progress">-</div><div class="l">track progress</div></div>
<div class="stat"><div class="v" id="racetime">-</div><div class="l">race time</div></div>
<div class="stat"><div class="v" id="reward">-</div><div class="l">episode reward</div></div>
<div class="stat"><div class="v" id="period">-</div><div class="l">step period</div></div>
<div class="stat"><div class="v" id="mode">-</div><div class="l">mode</div></div>
</div></section>
<section class="card"><h2>Decision <span id="expl" style="color:var(--muted);text-transform:none"></span></h2><div id="qvals"></div></section>
<section class="card"><h2>Episodes</h2><canvas id="epChart"></canvas>
<table><thead><tr><th>time</th><th>map</th><th>progress</th><th>finish</th><th>reward</th><th>steps</th><th>mode</th></tr></thead><tbody id="eptable"></tbody></table></section>
<section class="card"><h2>Learner</h2><canvas id="lossChart"></canvas></section>
<section class="card params" style="grid-column:1/-1"><h2>Parameters <span id="msg"></span></h2>
<div id="master" class="master"><input type="checkbox" id="p_master_learn"><label for="p_master_learn"><b>Master-learn</b> — I drive, the AI watches and records my runs. <small>Takes effect at the next episode: restart the race (Delete) when the log says it is waiting for you.</small></label></div>
<div id="paramrows"></div><div style="margin-top:10px"><button id="apply">Apply</button></div></section>
</main>
<script>
const SCHEMA = __SCHEMA__;
const $ = id => document.getElementById(id);
const ACTION_NAMES = __ACTIONS__;
let params = {}, dirty = false, lastFrameId = null;
function buildParams(){
  const rows = $('paramrows'); let group = null;
  for (const p of SCHEMA){
    if (p.name === 'master_learn') continue;
    if (p.group !== group){ group = p.group; const g = document.createElement('div'); g.className='group'; g.textContent = group; rows.appendChild(g); }
    const row = document.createElement('div'); row.className='row';
    const lab = document.createElement('label'); lab.htmlFor = 'p_'+p.name; lab.innerHTML = `${p.name}<small>${p.label}</small>`;
    let inp;
    if (p.type === 'choice'){ inp = document.createElement('select'); for (const c of p.choices){ const o=document.createElement('option'); o.value=c; o.textContent=c; inp.appendChild(o);} }
    else { inp = document.createElement('input'); inp.type='number'; inp.min=p.min; inp.max=p.max; inp.step=p.step; }
    inp.id = 'p_'+p.name; inp.addEventListener('input', () => { dirty = true; $('msg').textContent='unsaved changes'; });
    row.appendChild(lab); row.appendChild(inp); rows.appendChild(row);
  }
  $('p_master_learn').addEventListener('change', () => { dirty = true; $('msg').textContent='unsaved changes'; });
}
function showParams(p){
  if (dirty) return; params = p;
  for (const s of SCHEMA){ const el = $('p_'+s.name); if (!el) continue; if (s.type==='bool') el.checked = !!p[s.name]; else el.value = p[s.name]; }
  $('master').classList.toggle('on', !!p.master_learn);
}
$('apply').onclick = async () => {
  const body = {};
  for (const s of SCHEMA){ const el = $('p_'+s.name); if (!el) continue; body[s.name] = s.type==='bool' ? el.checked : el.value; }
  $('apply').disabled = true;
  try {
    const r = await fetch('/api/params', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    if (r.ok){ dirty = false; $('msg').textContent = 'applied ' + new Date().toLocaleTimeString(); showParams(await r.json()); }
    else $('msg').textContent = 'error ' + r.status + ' (your edits are kept)';
  } catch (e) { $('msg').textContent = 'error: ' + e + ' (your edits are kept)'; }
  finally { $('apply').disabled = false; }
};
const epChart = new Chart($('epChart'), {type:'line', data:{labels:[], datasets:[
  {label:'progress %', data:[], borderColor:'#4fc3f7', yAxisID:'y', tension:.2, pointRadius:2},
  {label:'reward', data:[], borderColor:'#ffb74d', yAxisID:'y2', tension:.2, pointRadius:2}]},
  options:{animation:false, responsive:true, scales:{y:{min:0,max:100,ticks:{color:'#8a94a6'}}, y2:{position:'right',ticks:{color:'#8a94a6'},grid:{drawOnChartArea:false}}, x:{ticks:{color:'#8a94a6',maxTicksLimit:8}}}, plugins:{legend:{labels:{color:'#e6e9ef'}}}}});
const lossChart = new Chart($('lossChart'), {type:'line', data:{labels:[], datasets:[
  {label:'loss', data:[], borderColor:'#ef5350', tension:.2, pointRadius:0},
  {label:'td error', data:[], borderColor:'#4fc3f7', tension:.2, pointRadius:0}]},
  options:{animation:false, responsive:true, scales:{y:{type:'logarithmic',ticks:{color:'#8a94a6'}}, x:{ticks:{color:'#8a94a6',maxTicksLimit:8}}}, plugins:{legend:{labels:{color:'#e6e9ef'}}}}});
function fmtTime(ms){ if (ms==null) return '-'; const s = ms/1000; return (s<0?'-':'') + Math.floor(Math.abs(s)/60) + ':' + (Math.abs(s)%60).toFixed(2).padStart(5,'0'); }
function render(d){
  $('run').textContent = d.run; $('envname').textContent = d.env || '-';
  if (!$('status').classList.contains('off')) $('status').textContent = (d.step_age != null && d.step_age > 3) ? 'live, no step for ' + Math.round(d.step_age) + ' s' : 'live';
  const l = d.learner || {}; $('learner').textContent = l.batches!=null ? `${l.batches} batches, ${(l.batches_per_s||0).toFixed(1)}/s, lr ${l.lr? l.lr.toExponential(1):'-'}` : 'burn-in';
  $('buffer').textContent = `${d.buffer_size||0}${d.demo_count? ' (' + d.demo_count + ' demos)':''}`;
  const s = d.step; if (s){
    $('speed').textContent = Math.round(s.speed); $('progress').textContent = (100*s.progress).toFixed(1)+'%';
    $('racetime').textContent = fmtTime(s.racetime); $('reward').textContent = (s.episode_reward||0).toFixed(1);
    $('period').textContent = s.step_period ? Math.round(s.step_period)+' ms' : '-';
    $('mode').textContent = s.master_learn ? 'watching you' : 'AI driving'; $('mode').style.color = s.master_learn ? 'var(--warn)' : 'var(--good)';
    $('expl').textContent = s.exploration ? `(${s.exploration}${s.action_tier!=null?', action tier '+s.action_tier.toFixed(2):''})` : '';
    const q = (s.q_values || []).map(v => v ?? 0); const mx = Math.max(...q.map(Math.abs), 1e-6); const box = $('qvals');
    if (box.children.length !== q.length){ box.innerHTML=''; q.forEach((_,i)=>{ const b=document.createElement('div'); b.className='bar'; b.innerHTML=`<span class="n">${ACTION_NAMES[i]||i}</span><div class="t"><div class="f"></div></div><span class="q" style="width:60px;text-align:right;font-family:ui-monospace,monospace"></span>`; box.appendChild(b); }); }
    q.forEach((v,i)=>{ const b = box.children[i]; b.classList.toggle('sel', i===s.action); b.classList.toggle('user', s.user_action===i); b.querySelector('.f').style.width = (50 + 50*v/mx) + '%'; b.querySelector('.q').textContent = v.toFixed(2); });
  }
  if (d.frame && d.frame_id !== lastFrameId){ $('frame').src = 'data:image/jpeg;base64,' + d.frame; lastFrameId = d.frame_id; }
  if (d.episodes){ epChart.data.labels = d.episodes.map((e,i)=>i+1); epChart.data.datasets[0].data = d.episodes.map(e=>100*(e.progress||0)); epChart.data.datasets[1].data = d.episodes.map(e=>e.total_reward||0); epChart.update();
    $('eptable').innerHTML = d.episodes.slice(-8).reverse().map(e=>`<tr><td>${(e.time||'').slice(11)}</td><td>${e.map||''}</td><td>${(100*(e.progress||0)).toFixed(1)}%</td><td>${e.finish_racetime? fmtTime(e.finish_racetime)+' '+(e.medal||''):'-'}</td><td>${(e.total_reward||0).toFixed(1)}</td><td>${e.total_step_count||''}</td><td>${e.demo?'you':'AI'}</td></tr>`).join(''); }
  if (d.metrics){ lossChart.data.labels = d.metrics.map(m=>m.batches); lossChart.data.datasets[0].data = d.metrics.map(m=>m.loss); lossChart.data.datasets[1].data = d.metrics.map(m=>m.mean_errors); lossChart.update(); }
  if (d.params) showParams(d.params);
}
function connect(){
  const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');
  ws.onopen = () => { $('status').textContent='live'; $('status').classList.remove('off'); };
  ws.onmessage = ev => render(JSON.parse(ev.data));
  ws.onclose = () => { $('status').textContent='disconnected, retrying…'; $('status').classList.add('off'); setTimeout(connect, 2000); };
}
buildParams(); connect();
</script></body></html>"""


def _finite(obj):
    "JSON has no NaN/Infinity: replace non-finite floats by None (the page shows a gap instead of freezing)."
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


class Viewer(ThreadServer):
    def __init__(self, training, port=2014, action_names=None):
        self.training = training
        self.latest_step = None
        self.frame = None
        self.frame_id = 0
        self._last_step_time = None
        self.episodes = []
        self._episodes_mtime = None
        self._episodes_time = 0.0
        threading.Thread(target=self._drain, daemon=True, name="viewer-drain").start()

        page = PAGE.replace("__SCHEMA__", json.dumps(SCHEMA)).replace("__ACTIONS__", json.dumps(action_names or []))
        app = FastAPI()

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return page

        @app.get("/api/state")
        async def state():
            return self.snapshot(with_frame=True)

        @app.post("/api/params")
        async def set_params(request: Request):
            values = self.training.params.update(**(await request.json()))
            logging.info(f"Viewer: parameters updated {values}")
            return values

        @app.websocket("/ws")
        async def ws(websocket: WebSocket):
            await websocket.accept()
            sent_frame = None
            try:
                while True:
                    snap = self.snapshot(with_frame=self.frame_id != sent_frame)
                    sent_frame = self.frame_id
                    await websocket.send_text(json.dumps(snap))
                    await asyncio.sleep(0.2)
            except (WebSocketDisconnect, RuntimeError):
                pass

        super().__init__(app, host="127.0.0.1", port=port, log_level="error")
        logging.info(f"Viewer running on http://127.0.0.1:{self.port}")

    def _drain(self):
        queue = self.training.viewer_queue
        while True:
            try:
                payload = queue.get()
            except (EOFError, OSError):
                return
            if "frame" in payload:
                self.frame = payload.pop("frame")
                self.frame_id += 1
            self.latest_step = payload
            self._last_step_time = time.time()

    def _episode_tail(self, n=60):
        path = Path(self.training.save_dir) / "episodes.jsonl"
        if time.time() - self._episodes_time < 2:
            return self.episodes
        self._episodes_time = time.time()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return self.episodes
        if mtime != self._episodes_mtime:
            self._episodes_mtime = mtime
            lines = deque(path.open(encoding="utf-8"), maxlen=n)
            episodes = []
            for line in lines:
                try:
                    episodes.append(json.loads(line))
                except ValueError:
                    pass
            self.episodes = episodes
        return self.episodes

    def snapshot(self, with_frame=False):
        t = self.training
        metrics = list(t.recent_metrics)
        learner = dict(metrics[-1]) if metrics else {}
        if len(metrics) >= 2:
            a, b = metrics[-min(len(metrics), 15)], metrics[-1]
            dt = b["_time"] - a["_time"]
            learner["batches_per_s"] = (b["batches"] - a["batches"]) / dt if dt > 0 else 0.0
        learner.pop("_time", None)
        snap = dict(
            run=getattr(t, "group", "?"),
            env=self.latest_step.get("env") if self.latest_step else None,
            step=self.latest_step,
            learner=learner,
            metrics=[{k: m[k] for k in ("batches", "loss", "mean_errors")} for m in metrics[-300:]],
            buffer_size=len(t.replay_buffer),
            demo_count=t.replay_buffer.demo_count(),
            episodes=self._episode_tail(),
            params=t.params.as_dict(),
            frame_id=self.frame_id,
            step_age=None if self._last_step_time is None else time.time() - self._last_step_time,
        )
        if with_frame and self.frame is not None:
            snap["frame"] = self.frame
        return _finite(snap)
