import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from bike_agent import FIXTURES, SecurityConfig, run_bike_agent  # noqa: E402

logger = logging.getLogger("bike_app")
DEFAULT_URL = os.environ.get("BIKE_PRICING_URL", "https://capitalbikeshare.com/pricing")
MAX_UPLOAD_BYTES = 8_000_000

app = FastAPI(title="Bike-share pricing agent (HW7 Part 4)")
if FIXTURES.is_dir():
    app.mount("/fixtures", StaticFiles(directory=str(FIXTURES)), name="fixtures")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bike-Share Pricing Agent</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2230;--mute:#667085;--line:#dde1e8;--accent:#1d6fd6;--good:#157f3b;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--card:#1b2029;--ink:#e8ebf1;--mute:#9aa4b5;--line:#2c3441;--accent:#5aa2ff;--good:#4cc27a;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mute);margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
form{display:grid;gap:10px}label{font-weight:600;font-size:13px;display:block;margin-bottom:3px}
input[type=text],input[type=file]{width:100%;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media (max-width:700px){.row{grid-template-columns:1fr}}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:10px 20px;font-weight:600;cursor:pointer}button:disabled{opacity:.5}
.metrics{display:flex;flex-wrap:wrap;gap:10px}.m{flex:1 1 140px;border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.m b{display:block;font-size:20px}.m span{color:var(--mute);font-size:12px}
.decision{font-size:24px;font-weight:700}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left}
.ev{border-left:3px solid var(--line);padding:4px 10px;margin:6px 0;font-size:13px;white-space:pre-wrap;word-break:break-word}
.ev.action{border-color:var(--accent)}.ev.observation{border-color:var(--mute)}.ev.final{border-color:var(--good)}
.tag{font-weight:700;text-transform:uppercase;font-size:11px;color:var(--mute)}.ok{color:var(--good)}.no{color:var(--bad)}
details{margin-top:6px}small{color:var(--mute)}
</style></head><body><main>
<h1>Bike-Share Pricing Agent</h1><p class="sub">Monthly membership or pay per ride? Upload trips, give the pricing page, press Run. &middot; Alyssa Gomez, DATA260 HW7</p>
<div class="card"><form id="f">
<div class="row"><div><label for="trips">Trip CSV (one upload)</label><input id="trips" type="file" accept=".csv" required></div>
<div><label for="label">Scenario name (used for saved files)</label><input id="label" type="text" value="scenario" pattern="[A-Za-z0-9_\\-]{1,40}"></div></div>
<div><label for="url">Pricing page URL</label><input id="url" type="text" value="__URL__" required></div>
<details><summary>Security switches (Part 5)</summary>
<label><input id="pd" type="checkbox" checked> Prompt defense: label retrieved text as untrusted</label>
<label><input id="td" type="checkbox" checked> Tool defense: csv_sql allows one read-only SELECT; answers containing raw trip ids are withheld</label></details>
<div><button id="run" type="submit">Run</button> <span id="status" class="sub"></span></div></form></div>
<div class="card"><div class="tag">Metrics</div><div class="metrics" id="metrics"><small>Run the agent to see step count, total time and stop reason.</small></div></div>
<div class="row"><div class="card"><div class="tag">Timeline: tool calls and observations</div><div id="timeline"></div></div>
<div class="card"><div class="tag">Results</div><div id="results"><small>No run yet.</small></div></div></div>
</main><script>
const $=id=>document.getElementById(id);
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function table(head,rows){const t=el('table');const h=el('tr');head.forEach(x=>h.append(el('th','',x)));t.append(h);
 rows.forEach(r=>{const tr=el('tr');r.forEach(c=>tr.append(el('td','',String(c))));t.append(tr)});return t}
function money(x){return (x===null||x===undefined)?'n/a':'$'+Number(x).toFixed(2)}
function metrics(m){const box=$('metrics');box.replaceChildren();
 [['Steps',m.steps],['Total time',m.total_time_s+' s'],['Stop reason',m.stop_reason],['Tool calls',m.tool_calls],['Verifier retries',m.retries||0]].forEach(([k,v])=>{
  const d=el('div','m');d.append(el('b','',v),el('span','',k));box.append(d)})}
function timeline(items){const box=$('timeline');box.replaceChildren();
 items.forEach((e,i)=>{const d=el('div','ev '+e.kind);d.append(el('span','tag',(i+1)+'. '+e.kind+(e.tool?' - '+e.tool:'')+'  ['+e.t+' s]'));
  const body=e.kind==='action'?JSON.stringify(e.args):(e.content||'');d.append(el('div','',body));box.append(d)})}
function results(r){const box=$('results');box.replaceChildren();
 const a=r.answer, c=r.independent_check;
 if(!a){box.append(el('div','no','No usable answer: '+(r.answer_problem||r.error||'unknown')));if(r.raw_final_text)box.append(el('pre','',r.raw_final_text));return}
 box.append(el('div','decision',a.decision||'(no decision)'));
 box.append(el('p','',a.justification||''));
 if(c){box.append(el('div','tag','Cost comparison (recomputed in code from the price parameters the agent found)'));
  box.append(table(['','Pay per use','Membership'],[['Total',money(c.payg_total),money(c.member_total)],
   ['Membership fees ('+c.months+' mo)','-',money(c.member_fees)],['Residual per-ride charges','-',money(c.member_residual)]]));
  box.append(el('p','','Cheaper: '+(c.cheaper==='membership'?'membership':'pay per use')+' by '+money(c.difference)+'. Break-even: '+
   (c.break_even_rides_per_month??'n/a')+' rides/month ('+(c.break_even_minutes_per_month??'n/a')+' min/month) vs actual '+c.actual_rides_per_month+' rides/month ('+c.actual_minutes_per_month+' min/month).'));
  if(r.price_problem)box.append(el('p','no','Price check: '+r.price_problem));
  const ok=r.decision_agrees_with_check;box.append(el('p',ok?'ok':'no',ok?'Agent decision agrees with the independent check.':'Agent decision DISAGREES with the independent check.'));
  box.append(el('div','tag','By week'));box.append(table(['Week of','Rides','Avg min','Pay-per-use spend','Membership residual'],
   c.weekly.map(w=>[w.week_start,w.rides,w.avg_minutes,money(w.payg_spend),money(w.member_residual)])))}
 else box.append(el('div','no','Independent check unavailable: '+(r.answer_problem||'')));
 if(a.costs)box.append(el('p','','Agent-reported totals: pay per use '+money(a.costs.pay_per_use_total)+', membership '+money(a.costs.membership_total)));
 box.append(el('div','tag','Citations'));
 (r.citations||[]).forEach(x=>{const p=el('p');p.append(el('span',x.verified?'ok':'no',x.verified?'[verified] ':'[not found in snapshot] '),document.createTextNode((x.id||'')+' '+(x.text||'')))
  p.append(document.createElement('br'),el('small','',(x.source||'')));box.append(p)});
 if(r.snapshot){box.append(el('p','','Pricing page: '+r.snapshot.url+' | captured '+r.snapshot.captured_at+' | SHA-256 '+r.snapshot.sha256))}
 box.append(el('div','tag','Assumptions and caveats'));const ul=el('ul');(a.assumptions||[]).forEach(x=>ul.append(el('li','',x)));box.append(ul);
 const lr=r.load_report;box.append(el('small','','Loaded '+lr.rows_loaded+' rides; skipped '+JSON.stringify(lr.rows_skipped)+'.'));
 if(r.leaked_ride_ids&&r.leaked_ride_ids.length)box.append(el('p','no','WARNING: '+r.leaked_ride_ids.length+' ride ids appeared in the agent answer'+(r.guard_blocked?' (withheld by the output guard).':'.')'))}
$('f').addEventListener('submit',async ev=>{ev.preventDefault();const b=$('run'),s=$('status');b.disabled=true;s.textContent='Running... this can take a minute or two.';
 const fd=new FormData();fd.append('trips',$('trips').files[0]);fd.append('url',$('url').value);fd.append('label',$('label').value);
 fd.append('prompt_defense',$('pd').checked);fd.append('tool_defense',$('td').checked);
 try{const resp=await fetch('/api/run',{method:'POST',body:fd});const r=await resp.json();
  if(!resp.ok){s.textContent='Error: '+(r.error||resp.status)}else{s.textContent='Done.';metrics(r.metrics);timeline(r.timeline);results(r)}}
 catch(e){s.textContent='Request failed: '+e}finally{b.disabled=false}});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """The single page."""
    return PAGE.replace("__URL__", DEFAULT_URL)


@app.post("/api/run")
async def run(trips: UploadFile = File(...), url: str = Form(...), label: str = Form("scenario"),
              prompt_defense: bool = Form(True), tool_defense: bool = Form(True)):
    """Run the agent on the uploaded CSV and the pricing URL."""
    data = await trips.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "the CSV is larger than 8 MB"}, status_code=413)
    safe_label = re.sub(r"[^A-Za-z0-9_\-]", "_", label)[:40] or "scenario"
    security = SecurityConfig(prompt_defense, tool_defense)
    try:
        return await run_in_threadpool(run_bike_agent, data.decode("utf-8-sig", errors="replace"), url,
                                       label=safe_label, security=security)
    except ValueError as exc:  # unreadable CSV
        return JSONResponse({"error": str(exc)}, status_code=400)