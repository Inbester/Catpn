// Synthetic but internally consistent backtest dataset (1h bars, 30 days)
(function(root){
function gen(SEED,KP,T0,OKP){
let seed=SEED;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
const gauss=()=>{let u=0,v=0;while(!u)u=rnd();while(!v)v=rnd();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)};
const K=KP||[[0,84300],[120,82500],[240,78200],[330,76100],[400,75400],[480,80500],[600,84200],[720,85100]];
const tgt=t=>{for(let k=1;k<K.length;k++){if(t<=K[k][0]){const [a,pa]=K[k-1],[b,pb]=K[k];return pa+(pb-pa)*(t-a)/(b-a)}}return K[K.length-1][1]};
const N=720;const B=[];let noise=0;let prev=K[0][1];
const t0=(T0||Date.UTC(2025,2,21,0,0,0))-3.5*3600e3; // 1404/01/01 00:00 Tehran
for(let i=0;i<N;i++){noise=noise*0.93+gauss()*0.0042;const c=tgt(i)*(1+noise);const o=prev;const h=Math.max(o,c)*(1+Math.abs(gauss())*0.0022);const l=Math.min(o,c)*(1-Math.abs(gauss())*0.0022);B.push({t:t0+i*3600e3,o,h,l,c,v:300+rnd()*900});prev=c}
// trades
const T=[];let i=30;
while(i<N-14){const e=i+1+Math.floor(rnd()*3);if(e>=N-13)break;const m=B[e+8].c/B[e].c-1;const ok=rnd()<(OKP||0.54);const dir=(ok?Math.sign(m):-Math.sign(m))||1;
 const hold=ok?3+Math.floor(rnd()*9):1+Math.floor(rnd()*5);const x=Math.min(e+hold,N-1);
 const ep=B[e].c,xp=B[x].c;let mae=0,mfe=0;for(let k=e+1;k<=x;k++){const lo=B[k].l/ep-1,hi=B[k].h/ep-1;if(dir>0){mae=Math.min(mae,lo);mfe=Math.max(mfe,hi)}else{mae=Math.min(mae,-hi);mfe=Math.max(mfe,-lo)}}
 const r=dir*(xp/ep-1);
 // funding crossings (00,08,16 UTC)
 let fund=0;for(let k=e+1;k<=x;k++){const hr=new Date(B[k].t).getUTCHours();if(hr%8===0){const rate=0.0001*(0.5+rnd()*1.6)*(rnd()<0.15?-1:1);fund+= -dir*rate}}
 T.push({dir,e,x,ep,xp,r,mae,mfe,fund,sig:r>0?(ok&&hold>6?'Take profit':'Opposite signal'):(hold<=2?'Stop loss':'Time exit')});
 i=x;}
return {B,T,N};
}
function sim(D,L,opt){opt=opt||{};const mf=0.1;let eq=10000;const curve=[eq];let fees=0,fundPaid=0,fundRecv=0,slip=0,liq=0,gross=0;const rows=[];
 for(const t of D.T){const notional=eq*mf*L;const feeRate=(t.r>0?0.0002:0.0006)+0.0006;const sl=0.0002;
  let pnl;const liqTh=1/L-0.005;let isLiq=false;
  if(-t.mae>=liqTh){pnl=-eq*mf;isLiq=true;liq++}
  else{pnl=notional*t.r}
  const fee=notional*feeRate,sp=notional*sl,fu=notional*t.fund;
  gross+=pnl;fees+=fee;slip+=sp;if(fu<0)fundPaid+=-fu;else fundRecv+=fu;
  const net=pnl-fee-sp+(isLiq?0:fu);const before=eq;eq+=net;curve.push(eq);
  rows.push({...t,notional,pnl,fee,fu:isLiq?0:fu,net,eq,pct:net/before,liq:isLiq,runup:t.mfe*notional,dd:t.mae*notional});}
 let peak=curve[0],mdd=0;const ddc=curve.map(v=>{peak=Math.max(peak,v);const d=v/peak-1;mdd=Math.min(mdd,d);return d});
 const wins=rows.filter(r=>r.net>0),loss=rows.filter(r=>r.net<=0);
 const gp=wins.reduce((a,r)=>a+r.net,0),gl=-loss.reduce((a,r)=>a+r.net,0);
 const rets=rows.map(r=>r.pct);const mu=rets.reduce((a,b)=>a+b,0)/rets.length;const sd=Math.sqrt(rets.reduce((a,b)=>a+(b-mu)**2,0)/rets.length);
 const tpy=rows.length*12;const sharpe=mu/sd*Math.sqrt(tpy);
 const dn=Math.sqrt(rets.filter(x=>x<0).reduce((a,b)=>a+b*b,0)/rets.length);const sortino=mu/dn*Math.sqrt(tpy);
 let st=0,maxW=0,maxL=0;rows.forEach(r=>{if(r.net>0){st=st>0?st+1:1;maxW=Math.max(maxW,st)}else{st=st<0?st-1:-1;maxL=Math.max(maxL,-st)}});
 return {L,rows,curve,ddc,eq,net:eq-10000,netPct:eq/10000-1,mdd,pf:gp/gl,win:wins.length/rows.length,nW:wins.length,n:rows.length,gp,gl,fees,slip,fundPaid,fundRecv,liq,gross,sharpe,sortino,avgW:gp/wins.length,avgL:gl/loss.length,maxW,maxL,
  longs:rows.filter(r=>r.dir>0),shorts:rows.filter(r=>r.dir<0),worstMae:Math.min(...rows.map(r=>r.mae))};}
root.BT={gen,sim};
})(typeof window!=='undefined'?window:globalThis);
