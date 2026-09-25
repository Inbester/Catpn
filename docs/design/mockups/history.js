(function(){
if(!new URLSearchParams(location.search).get('hist'))return;
const P='<svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;flex:none">';
const ic={cloud:P+'<path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.2 9.1 4.5 4.5 0 0 0 7 18z"/><path d="M9.5 13.5l2 2 3.5-3.5"/></svg>',
 line:P+'<path d="M2 12h20"/><circle cx="12" cy="12" r="1.8"/></svg>',ind:P+'<path d="M2 12l4-4 3 3 5-6"/><path d="M2 16h12"/></svg>',
 eye:P+'<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><path d="M4 4l16 16"/></svg>',
 tf:P+'<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>',st:P+'<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/></svg>',
 res:P+'<path d="M4 20h16"/><rect x="6" y="11" width="3" height="6"/><rect x="11" y="7" width="3" height="10"/><rect x="16" y="4" width="3" height="13"/></svg>',
 star:P+'<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" fill="currentColor"/></svg>',
 gear:P+'<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21"/></svg>',
 restore:P+'<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 4v5h5"/></svg>',dev:P+'<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
 phone:P+'<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/></svg>'};
const css=`
.svst{display:flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:6px;color:#7D848E;font:500 12px Inter;white-space:nowrap;flex:none}
.svst svg{color:#2EBD85}
.hs{display:grid;grid-template-rows:56px auto minmax(0,1fr) auto;min-height:0;height:100%}
.hsub{white-space:nowrap;display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid #1C1F23;font-size:12px;color:#7D848E}
.hsub svg{color:#2EBD85}
.hsub b{color:#E7E9EC;font-weight:500}
.hf{display:flex;gap:4px;padding:10px 16px 4px}
.hf span{font:500 11px Inter;color:#7D848E;padding:4px 8px;border-radius:5px}
.hf span.on{background:#1A1D21;color:#E7E9EC}
.hl{overflow:hidden;padding-bottom:8px}
.hd2{font:500 11px Inter;letter-spacing:.06em;text-transform:uppercase;color:#4A5059;padding:12px 16px 6px}
.hi{display:grid;grid-template-columns:40px 20px minmax(0,1fr) auto;gap:8px;align-items:center;padding:7px 16px;position:relative}
.hi .t{font:400 11px 'JBM',monospace;color:#7D848E}
.hi .i{color:#7D848E;display:grid;place-items:center}
.hi b{font-weight:500;font-size:12px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hi small{display:block;font-size:11px;color:#4A5059;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hi .tag{font:600 9px Inter;letter-spacing:.05em;padding:2px 5px;border-radius:3px;background:#1A1D21;color:#7D848E}
.hi.cur{background:#16191C}
.hi.cur::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:2px;background:#2EBD85}
.hi.hov{background:#16191C}
.hi .rb{display:flex;align-items:center;gap:4px;height:24px;padding:0 8px;border-radius:5px;box-shadow:0 0 0 1px #1C1F23 inset;font:500 11px Inter;color:#E7E9EC}
.hi.named b{color:#E7E9EC}
.hi.named .i{color:#D9B26A}
.hft{border-top:1px solid #1C1F23;padding:12px 16px;display:grid;gap:10px}
.hft .b2{height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;gap:6px;font:600 12px Inter;background:#E7E9EC;color:#0B0C0E}
.hft small{font-size:11px;color:#4A5059;line-height:15px}
.devs{display:flex;gap:10px;font-size:11px;color:#7D848E}
.devs span{display:flex;align-items:center;gap:4px}
`;
function run(){
 const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
 const fill=document.querySelector('#bar .fill');
 if(fill){const d=document.createElement('span');d.className='svst';d.innerHTML=ic.cloud+'Saved';fill.after(d);}
 const side=document.getElementById('side');
 const it=(t,i,title,sub,tag,cls,act)=>`<div class="hi ${cls||''}"><span class="t">${t}</span><span class="i">${ic[i]}</span><span><b>${title}</b><small>${sub}</small></span>${act||(tag?`<span class="tag">${tag}</span>`:'<span></span>')}</div>`;
 side.innerHTML=`<div class="hs">
 <div class="sh"><div class="tabs"><span>Watchlist</span><span>Objects</span><span class="on">History</span></div></div>
 <div><div class="hsub">${ic.cloud}<span><b>Every change is saved</b> · device + account</span></div>
  <div class="hf"><span class="on">All</span><span>Chart</span><span>Strategy</span><span>Research</span><span>Settings</span></div></div>
 <div class="hl">
  <div class="hd2">Today</div>
  ${it('14:18','line','Alert line at 62,300.0','BTCUSDT · 15m','CHART','cur','<span class="tag" style="background:rgba(46,189,133,.14);color:#4FD19E">NOW</span>')}
  ${it('14:06','ind','Added RSI 14','BTCUSDT · 15m','CHART')}
  ${it('13:52','eye','Hid Volume','pane 1','CHART','hov','<span class="rb">'+ic.restore+'Restore</span>')}
  ${it('13:40','tf','Timeframe 1h → 15m','layout “Default”','CHART')}
  ${it('13:15','st','EMA Trend + RSI Pullback v4 draft','2 conditions changed · diff vs v3','STRATEGY')}
  ${it('12:48','res','Discovery results saved','Multi-signal Confluence · 11 rules','RESEARCH')}
  ${it('12:30','gear','Countdown to bar close on','chart settings','SETTINGS')}
  <div class="hd2">Yesterday</div>
  ${it('22:10','star','“Scalp 15m” — named version','layout + 6 drawings + 3 indicators','NAMED','named')}
  ${it('18:32','line','Moved support to 63,512.3','BTCUSDT · 15m','CHART')}
 </div>
 <div class="hft"><span class="b2">${ic.star.replace('fill="currentColor"','')}Name this version</span>
  <div class="devs"><span>${ic.dev}Laptop · synced</span><span>${ic.phone}Phone · 2 min ago</span></div>
  <small>Every change kept 90 days · named versions forever · Ctrl+Z works across refresh</small></div>
 </div>`;
 side.style.gridTemplateRows='1fr';
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(run,0));else setTimeout(run,0);
})();
