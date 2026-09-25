(function(root){
function year(){
 const seeds=[123,21,5,8,13,34,55,89,144,233,377,610];let price=84300;const B=[],T=[];
 seeds.forEach((sd,m)=>{let s2=sd*7+3;const r=()=>(s2=(s2*16807)%2147483647)/2147483647;
  const K=[[0,price]];let p=price;[120,240,360,480,600,720].forEach(t=>{p=p*(1+(r()-.5)*0.09);K.push([t,p])});
  const D=BT.gen(sd,K,Date.UTC(2025,2,21)+m*30*864e5,root.RS_OKP||0.515);const off=B.length;
  D.B.forEach(b=>B.push(b));D.T.forEach(t=>T.push({...t,e:t.e+off,x:t.x+off}));price=D.B[D.B.length-1].c;});
 return {B,T,N:B.length};}
function simX(D,L,mode,opt){opt=opt||{};const mf=opt.mf||0.1,fee=opt.feeMul||1,slp=opt.slipMul||1,fund=opt.fundAdd||0;let eq=10000;const curve=[eq];let fees=0,slip=0,fp=0,fr=0,liq=0,gross=0,worst=0;const rows=[];
 for(const t of D.T){if(eq<=1){curve.push(eq);continue}const notional=eq*mf*L;const fr_=((t.r>0?0.0002:0.0006)+0.0006)*fee;const sr=0.0002*slp;
  const th=mode==='cross'?(1/(mf*L)-0.005):(1/L-0.005);let pnl,isL=false;
  if(-t.mae>=th){isL=true;liq++;pnl=mode==='cross'?-eq:-eq*mf}else pnl=notional*t.r;
  const fcost=notional*fr_,scost=notional*sr;const holdF=t.fund+(fund?-t.dir*fund*Math.max(0,Math.round((t.x-t.e)/8)):0);const fu=isL?0:notional*holdF;
  gross+=pnl;fees+=fcost;slip+=scost;if(fu<0)fp+=-fu;else fr+=fu;const net=pnl-fcost-scost+fu;const before=eq;eq=Math.max(0,eq+net);curve.push(eq);worst=Math.min(worst,net/before);
  rows.push({...t,net,pct:net/before,notional,liq:isL,maeUsd:t.mae*notional,fu});}
 let pk=curve[0],mdd=0;curve.forEach(v=>{pk=Math.max(pk,v);mdd=Math.min(mdd,v/pk-1)});
 return {L,mode,eq,net:eq/10000-1,mdd,liq,fees,slip,fp,fr,gross,worst,rows,curve};}
root.RS={year,simX};
})(typeof window!=='undefined'?window:globalThis);
