require('./btdata.js');
for(const s of [7,11,23,42,99,123,321,777,2025,4242]){const D=BT.gen(s);const r=[1,5,10,20,50].map(L=>{const x=BT.sim(D,L);return `${L}x net ${(x.netPct*100).toFixed(1)}% dd ${(x.mdd*100).toFixed(1)}% pf ${x.pf.toFixed(2)} win ${(x.win*100).toFixed(0)} n ${x.n} liq ${x.liq}`});console.log(s,'| bh',((D.B[719].c/D.B[0].c-1)*100).toFixed(1),'|',r.join(' | '))}
