require('./btdata.js');
const K2=[[0,71200],[150,69800],[300,72100],[420,68400],[560,66900],[720,66500]];
const T0=Date.UTC(2026,2,21);
const ref=BT.sim(BT.gen(123),10);
// MC band
function mc(rows,n,it=4000){let seed=5;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;const nets=[],dds=[];for(let k=0;k<it;k++){let eq=1,pk=1,md=0;for(let i=0;i<n;i++){const r=rows[Math.floor(rnd()*rows.length)].pct;eq*=1+r;pk=Math.max(pk,eq);md=Math.min(md,eq/pk-1)}nets.push(eq-1);dds.push(md)}nets.sort((a,b)=>a-b);dds.sort((a,b)=>a-b);const q=(a,p)=>a[Math.floor(p*(a.length-1))];return {n5:q(nets,.05),n50:q(nets,.5),n95:q(nets,.95),d5:q(dds,.05),d50:q(dds,.5)}}
for(const s of [3,5,8,13,21,34,55,89,144,233,377,610]){const D=BT.gen(s,K2,T0);const f=BT.sim(D,10);const b=mc(ref.rows,f.n);
console.log(s,'bh',((D.B[719].c/D.B[0].c-1)*100).toFixed(1),'net',(f.netPct*100).toFixed(2),'dd',(f.mdd*100).toFixed(2),'pf',f.pf.toFixed(2),'win',(f.win*100).toFixed(1),'n',f.n,'| band',(b.n5*100).toFixed(1),(b.n50*100).toFixed(1),(b.n95*100).toFixed(1),'dd5',(b.d5*100).toFixed(1))}
