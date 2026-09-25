require('./btdata.js');require('./rsdata.js');
const Y=RS.year();console.log('bars',Y.N,'trades',Y.T.length,'bh',((Y.B[Y.N-1].c/Y.B[0].c-1)*100).toFixed(1));
for(const mode of ['isolated','cross'])for(const L of [1,2,3,5,10,15,20,25,50,75,100]){const r=RS.simX(Y,L,mode);console.log(mode,L,'net',(r.net*100).toFixed(1),'dd',(r.mdd*100).toFixed(1),'liq',r.liq,'worst',(r.worst*100).toFixed(2),'fees',r.fees.toFixed(0),'gross',r.gross.toFixed(0))}
const maes=Y.T.map(t=>t.mae).sort((a,b)=>a-b);console.log('mae min',maes[0],'p5',maes[Math.floor(.05*maes.length)]);
