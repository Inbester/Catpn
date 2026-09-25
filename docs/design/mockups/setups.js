(function(){
if(new URLSearchParams(location.search).get('setup')!=='pick')return;
const css=`
.spk{display:inline-flex;align-items:center;gap:8px;height:32px;padding:0 10px;border-radius:8px;box-shadow:0 0 0 1px #7D848E inset;background:#1A1D21;font:500 13px Inter;color:#E7E9EC;white-space:nowrap}
.spk i{width:10px;height:10px;border-radius:3px;display:inline-block}
.spk small{font:400 11px 'JBM',monospace;color:#7D848E}
.spk svg{width:12px;height:12px;stroke:#7D848E;fill:none;stroke-width:1.8}
.sdrop{position:fixed;width:700px;background:#15171A;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.6),0 0 0 1px #262a30;z-index:70;overflow:hidden;font:400 13px/16px Inter;color:#E7E9EC}
.sdrop .s{display:flex;align-items:center;gap:8px;margin:10px 12px;height:36px;padding:0 10px;border-radius:8px;background:#0B0C0E;box-shadow:0 0 0 1px #1C1F23 inset;color:#7D848E;font-size:12px}
.sdrop .row{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px 16px;position:relative}
.sdrop .row.on{background:#1A1D21}
.sdrop .row.on::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:2px;background:#E7E9EC}
.sdrop .row i{width:10px;height:10px;border-radius:3px}
.sdrop .row b{font-weight:500;display:block}
.sdrop .row small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;font:400 11px 'JBM',monospace;color:#7D848E;margin-top:3px}
.stg{display:flex;gap:4px}
.stg span{font:600 9px Inter;letter-spacing:.04em;padding:3px 5px;border-radius:3px;background:#1A1D21;color:#4A5059}
.stg span.ok{background:rgba(46,189,133,.14);color:#4FD19E}
.stg span.run{background:rgba(110,168,254,.16);color:#8DB8FF}
.stg span.warn{background:rgba(245,158,11,.16);color:#F5B544}
.stg span.bad{background:rgba(240,80,110,.14);color:#F37A92}
.sdrop .ft{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;border-top:1px solid #1C1F23;font-size:12px;color:#7D848E}
.sdrop .ft b{color:#E7E9EC;font-weight:500}
`;
function run(){
 const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
 const hd=document.querySelector('.rm .hd');if(!hd)return;const chip=hd.querySelector('.chip');
 const b=document.createElement('span');b.className='spk';b.innerHTML='<i style="background:#6EA8FE"></i>BTC 15m Trend <small>BTCUSDT · 15m · v3</small><svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>';
 chip.replaceWith(b);const pf=hd.querySelector('.chip.o');if(pf)pf.remove();
 const S=[['#6EA8FE','BTC 15m Trend','EMA Trend v3 · BTCUSDT 15m · 20% × 5×',[['RES','ok'],['BT','ok'],['FWD','ok'],['PAPER','run'],['ALERT','run'],['BOT','']],1],
  ['#D9B26A','BTC 1m Scalp','Micro Pullback v2 · BTCUSDT 1m · 10% × 3×',[['RES','ok'],['BT','ok'],['FWD','warn'],['PAPER',''],['ALERT','run'],['BOT','']]],
  ['#B48CF2','BTC 8h Funding','Funding Revert v2 · BTCUSDT 8h · 25% × 2×',[['RES','ok'],['BT','ok'],['FWD','ok'],['PAPER','ok'],['ALERT','run'],['BOT','run']]],
  ['#2EBD85','ETH 1h Swing','Confluence v1 · ETHUSDT 1h · 15% × 3×',[['RES','ok'],['BT','ok'],['FWD','run'],['PAPER',''],['ALERT',''],['BOT','']]],
  ['#7D848E','SOL 4h Squeeze','BB Squeeze v4 · SOLUSDT 4h · 10% × 2×',[['RES','ok'],['BT','ok'],['FWD','bad'],['PAPER',''],['ALERT',''],['BOT','']]]];
 const d=document.createElement('div');d.className='sdrop';
 d.innerHTML=`<div class="s"><svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/></svg>Search setups, coins, timeframes</div>`+
  S.map(s=>`<div class="row ${s[4]?'on':''}"><i style="background:${s[0]}"></i><span><b>${s[1]}</b><small>${s[2]}</small></span><span class="stg">${s[3].map(([t,c])=>`<span class="${c}">${t}</span>`).join('')}</span></div>`).join('')+
  `<div class="ft"><span><b>+ New setup</b> from a research result</span><span>Manage all setups →</span></div>`;
 document.body.appendChild(d);const r=b.getBoundingClientRect();d.style.left=r.left+'px';d.style.top=(r.bottom+8)+'px';
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(run,30));else setTimeout(run,30);
})();
