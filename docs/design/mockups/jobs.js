// Global jobs indicator overlay for mockups. Mode from ?jobs=tray|toast|ring
(function(){
const mode=(new URLSearchParams(location.search).get('jobs'))||'ring';
const P='<svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round">';
const ic={pause:P+'<path d="M9 6v12M15 6v12"/></svg>',stop:P+'<rect x="7" y="7" width="10" height="10" rx="1.5"/></svg>',play:P+'<path d="M8 5l11 7-11 7z"/></svg>',
 disc:P+'<path d="M4 20h16"/><rect x="6" y="11" width="3" height="6"/><rect x="11" y="7" width="3" height="10"/><rect x="16" y="4" width="3" height="13"/></svg>',
 bt:P+'<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/></svg>',
 fwd:P+'<path d="M4 12h12M12 6l6 6-6 6"/><path d="M20 5v14"/></svg>',
 check:P+'<path d="M5 12.5l4.5 4.5L19 7"/></svg>',x:P+'<path d="M6 6l12 12M18 6L6 18"/></svg>',
 arrow:P+'<path d="M9 6l6 6-6 6"/></svg>',cpu:P+'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>'};
const css=`
.jring{width:40px;height:40px;border-radius:8px;display:grid;place-items:center;position:relative;margin-bottom:4px}
.jring.on{background:#1A1D21}
.jring svg.r{position:absolute;inset:6px;width:28px;height:28px;transform:rotate(-90deg)}
.jring .t{font:500 9px 'JBM',monospace;color:#E7E9EC;letter-spacing:-.02em}
.jring .q{position:absolute;bottom:0;right:0;min-width:14px;height:14px;border-radius:7px;background:#E7E9EC;color:#0B0C0E;font:600 9px Inter;display:grid;place-items:center;padding:0 3px}
.jtray{position:fixed;left:64px;bottom:96px;width:392px;background:#15171A;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.55),0 0 0 1px #262a30;z-index:60;overflow:hidden;font:400 13px/16px Inter;color:#E7E9EC}
.jtray::before{content:"";position:absolute}
.jh{display:flex;align-items:center;justify-content:space-between;height:52px;padding:0 16px;border-bottom:1px solid #1C1F23}
.jh b{font-weight:600}.jh span{font-size:12px;color:#7D848E}
.js{font:500 11px Inter;letter-spacing:.06em;text-transform:uppercase;color:#4A5059;padding:14px 16px 6px}
.jr{display:grid;grid-template-columns:28px 1fr auto;gap:10px;padding:8px 16px;align-items:start}
.jr .i{width:28px;height:28px;border-radius:6px;background:#1A1D21;display:grid;place-items:center;color:#7D848E}
.jr b{font-weight:500;display:block}
.jr small{display:block;font-size:11px;color:#7D848E;margin-top:2px}
.jr .a{display:flex;gap:2px}
.jr .a span{width:28px;height:28px;border-radius:6px;display:grid;place-items:center;color:#7D848E}
.jr .lk{font:500 11px Inter;color:#E7E9EC;display:flex;align-items:center;gap:2px;height:28px}
.jb{grid-column:2/4;display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;margin-top:2px}
.jb i{height:4px;border-radius:2px;background:#1C1F23;overflow:hidden;display:block}
.jb i b{display:block;height:100%;border-radius:2px}
.jb em{font:500 11px 'JBM',monospace;font-style:normal;color:#E7E9EC}
.jb em small{display:inline;color:#7D848E;font-weight:400}
.jmeta{grid-column:2/4;display:flex;gap:12px;font:400 11px 'JBM',monospace;color:#7D848E;margin-top:2px}
.jf{border-top:1px solid #1C1F23;margin-top:8px;padding:12px 16px;font-size:11px;line-height:16px;color:#4A5059}
.jtoast{position:fixed;right:24px;bottom:24px;width:380px;background:#15171A;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.55),0 0 0 1px #262a30;z-index:60;padding:16px;display:grid;grid-template-columns:32px 1fr auto;gap:12px;font:400 13px/16px Inter;color:#E7E9EC}
.jtoast .ok{width:32px;height:32px;border-radius:8px;background:rgba(46,189,133,.14);color:#2EBD85;display:grid;place-items:center}
.jtoast b{font-weight:600;display:block}
.jtoast small{display:block;font-size:12px;color:#7D848E;margin-top:4px;line-height:17px}
.jtoast .btns{grid-column:2/4;display:flex;gap:8px;margin-top:4px}
.jtoast .btns span{height:30px;padding:0 12px;border-radius:8px;display:flex;align-items:center;font-weight:600;font-size:12px}
.jtoast .p{background:#E7E9EC;color:#0B0C0E}.jtoast .s{box-shadow:0 0 0 1px #1C1F23 inset;color:#7D848E;font-weight:500!important}
.jtoast .cl{color:#4A5059}
.jal{width:40px;height:36px;border-radius:8px;display:grid;place-items:center;position:relative;color:#7D848E;margin-bottom:6px}
.jal.on{background:#1A1D21;color:#E7E9EC}
.jal svg{width:18px;height:18px}
.jal .q{position:absolute;top:2px;right:2px;min-width:16px;height:16px;border-radius:8px;background:#2EBD85;color:#0B0C0E;font:700 9px Inter;display:grid;place-items:center;padding:0 4px;box-shadow:0 0 0 2px #0B0C0E}
.jsep{width:20px;height:1px;background:#1C1F23;margin:2px 0 8px}
.apop{position:fixed;left:64px;bottom:110px;width:400px;background:#15171A;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.55),0 0 0 1px #262a30;z-index:60;overflow:hidden;font:400 13px/16px Inter;color:#E7E9EC}
.ag{font:600 12px Inter;color:#E7E9EC;padding:12px 16px 4px;display:flex;justify-content:space-between;border-top:1px solid #1C1F23;margin-top:4px}
.ag em{font-style:normal;letter-spacing:0;text-transform:none;color:#7D848E;font-weight:400}
.ar{display:grid;grid-template-columns:8px 1fr auto;gap:10px;align-items:center;padding:7px 16px}
.ar .d{width:6px;height:6px;border-radius:50%;background:#2EBD85;box-shadow:0 0 0 3px rgba(46,189,133,.18)}
.ar b{font-weight:500;font-size:12px}
.ar small{display:block;font-size:11px;color:#7D848E;margin-top:1px}
.ar .t{font:400 11px 'JBM',monospace;color:#7D848E}
.sw{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:0}

`;
function mount(){
 const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
 const rail=document.querySelector('.rail');if(!rail)return;
 const sp=rail.querySelector('.spacer');
 const pct=mode==='toast'?100:61;const C=2*Math.PI*12;
 const ring=document.createElement('div');ring.className='jring'+(mode==='tray'?' on':'');
 ring.innerHTML=`<svg class="r" viewBox="0 0 28 28"><circle cx="14" cy="14" r="12" fill="none" stroke="#2C3036" stroke-width="2.5"/><circle cx="14" cy="14" r="12" fill="none" stroke="${mode==='toast'?'#2EBD85':'#E7E9EC'}" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="${C*pct/100} ${C}"/></svg>${mode==='toast'?`<span style="color:#2EBD85;display:grid;place-items:center">${ic.check}</span>`:`<span class="t">${pct}</span>`}${mode==='toast'?'':'<span class="q">2</span>'}`;
 sp.after(ring);
 const al=document.createElement('div');const amode=new URLSearchParams(location.search).get('alerts');al.className='jal'+(amode==='pop'?' on':'');
 al.innerHTML=P.replace('width:14px;height:14px','width:18px;height:18px')+'<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg><span class="q">9</span>';
 const sep=document.createElement('div');sep.className='jsep';
 ring.after(al);al.after(sep);
 if(amode==='pop'){const p=document.createElement('div');p.className='apop';
  const row=(t,sub,last)=>`<div class="ar"><span class="d"></span><span><b>${t}</b><small>${sub}</small></span><span class="t">${last}</span></div>`;
  p.innerHTML=`<div class="jh"><b>Active alerts · 9</b><span>watched on server</span></div>
  <div class="ag"><span><span class="sw" style="background:#6EA8FE"></span>BTC 15m Trend</span><em>BTCUSDT · 15m</em></div>${row('Strategy signals','long · short · exit · TP/SL → browser, Telegram ×3','33m')}${row('Drawdown beyond −8%','paper account','—')}
  <div class="ag"><span><span class="sw" style="background:#D9B26A"></span>BTC 1m Scalp</span><em>BTCUSDT · 1m</em></div>${row('Strategy signals','long · short · exit → Telegram DM','2m')}
  <div class="ag"><span><span class="sw" style="background:#B48CF2"></span>BTC 8h Funding</span><em>BTCUSDT · 8h · live bot</em></div>${row('Liquidation closer than 3%','bot position','—')}${row('Bot errors & disconnects','system','5d')}
  <div class="ag"><span>No setup</span><em>manual</em></div>${row('BTC crossing 62,300.0','price · from chart line','—')}${row('ETH above 3,500.00','price','—')}${row('SOL · RSI 14 below 30','indicator · 1h','1d')}${row('Funding above 0.05% / 8h','market','3d')}
  <div class="jf">Next checks: BTC 1m in 0:41 · BTC 15m in 11:13 · BTC 8h in 1:41:13</div>`;
  document.body.appendChild(p);}
 if(mode==='tray'){
  const t=document.createElement('div');t.className='jtray';
  const bar=(p,c)=>`<i><b style="width:${p}%;background:${c}"></b></i>`;
  t.innerHTML=`<div class="jh"><b>Jobs</b><span>2 active · keeps running across menus</span></div>
  <div class="js">Running</div>
  <div class="jr"><span class="i">${ic.disc}</span><span><b>Discover · Multi-signal Confluence</b><small>BTCUSDT 1h · 558,624 tests · This browser</small></span><span class="a"><span>${ic.pause}</span><span>${ic.stop}</span></span>
   <div class="jb">${bar(61,'#2EBD85')}<em>61% <small>· 4 s left</small></em></div>
   <div class="jmeta"><span>61,300 tests/s</span><span>CPU 74%</span><span>GPU 88%</span><span>RAM 4.2 GB</span></div></div>
  <div class="js">Queued</div>
  <div class="jr"><span class="i">${ic.bt}</span><span><b>Backtest · EMA Trend + RSI Pullback v4</b><small>BTCUSDT 15m · 1404/01 · starts after current job</small></span><span class="a"><span>${ic.x}</span></span>
   <div class="jb">${bar(0,'#7D848E')}<em><small>waiting</small></em></div></div>
  <div class="js">Paused</div>
  <div class="jr"><span class="i">${ic.disc}</span><span><b>Discover · My Indicator L1×L2</b><small>Tab was closed · saved checkpoint at 34%</small></span><span class="a"><span style="color:#E7E9EC">${ic.play}</span><span>${ic.x}</span></span>
   <div class="jb">${bar(34,'#F59E0B')}<em>34% <small>· resumable</small></em></div></div>
  <div class="js">Finished today</div>
  <div class="jr"><span class="i" style="color:#2EBD85">${ic.check}</span><span><b>Forward test · Farvardin 1404 vs 1405</b><small>Done 12 min ago · net +4.1% vs +7.9% last year</small></span><span class="lk">Open ${ic.arrow}</span></div>
  <div class="jr"><span class="i" style="color:#2EBD85">${ic.check}</span><span><b>Backtest · Bollinger Squeeze v4</b><small>Done 1 h ago · 212 trades</small></span><span class="lk">Open ${ic.arrow}</span></div>
  <div class="jf">Jobs run outside the page, so switching menus never stops them. Closing the tab pauses browser jobs; they resume from the last checkpoint. Local-agent and cloud jobs keep running.</div>`;
  document.body.appendChild(t);
 }
 if(mode==='toast'){
  const t=document.createElement('div');t.className='jtoast';
  t.innerHTML=`<span class="ok">${ic.check}</span><span><b>Discovery finished</b><small>Multi-signal Confluence · 558,624 tests in 9.2 s<br>37 pass FDR · <span style="color:#2EBD85">11 confirmed out-of-sample</span></small></span><span class="cl">${ic.x}</span>
  <div class="btns"><span class="p">View results</span><span class="s">Add best to strategy</span></div>`;
  document.body.appendChild(t);
 }
}
const go=()=>setTimeout(mount,0);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
window.__jobsMount=true;
})();
