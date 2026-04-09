
// ═══════════════ DATA ═══════════════
const H = [
  {n:'M4A1消音版 · 苔藓石英',w:'FN',wv:.0563,c:1610,p:1319,t:'weapon'},
  {n:'P2000 · 火灵',w:'FN',wv:.0607,c:1340,p:1388.5,t:'weapon'},
  {n:'M4A4 · 炼狱之火',w:'FT',wv:.1456,c:744,p:676.96,t:'weapon'},
  {n:'法玛斯 · 纪念碑',w:'FN',wv:.0347,c:710,p:648.9,t:'weapon'},
  {n:'法玛斯 · 纪念碑',w:'FN',wv:.0435,c:702,p:648.9,t:'weapon'},
  {n:'UMP-45 · 炽烈之炎',w:'FN',wv:.0633,c:390,p:323,t:'weapon'},
  {n:'UMP-45 · 炽烈之炎',w:'FN',wv:.0341,c:370,p:323,t:'weapon'},
  {n:'M4A4 · 都市 DDPAT',w:'FN',wv:.0649,c:410,p:377.4,t:'weapon'},
  {n:'MP7 · 死亡骷髅',w:'FT',wv:.1146,c:217,p:243.39,t:'weapon'},
  {n:'M4A4 · 龙王',w:'FT',wv:.1403,c:184,p:196.5,t:'weapon'},
  {n:'法玛斯 · 线路故障',w:'FN',wv:.0587,c:115.5,p:131,t:'weapon'},
  {n:'FN57 · 夜影',w:'FN',wv:.0576,c:140,p:135.5,t:'weapon'},
  {n:'M4A4 · 多边形编辑',w:'FT',wv:.1440,c:132,p:150,t:'weapon'},
  {n:'M4A4 · 多边形编辑',w:'FT',wv:.1376,c:129,p:150,t:'weapon'},
  {n:'M4A4 · 彼岸花',w:'FT',wv:.1411,c:127,p:134.99,t:'weapon'},
  {n:'双持贝瑞塔 · 街头抢匪',w:'FN',wv:.0585,c:54.9,p:50.78,t:'weapon'},
  {n:'M4A4 · 蚀刻领主',w:'FT',wv:.1215,c:7.65,p:8.92,t:'weapon'},

  {n:'海军上尉里克索尔',w:'大师',wv:0,c:377,p:250,t:'agent'},
  {n:'海军上尉里克索尔',w:'大师',wv:0,c:350,p:250,t:'agent'},
  {n:'海军上尉里克索尔',w:'大师',wv:0,c:317,p:250,t:'agent'},
  {n:'"蓝莓" 铅弹',w:'卓越',wv:0,c:213,p:168,t:'agent'},
  {n:'"蓝莓" 铅弹',w:'卓越',wv:0,c:189,p:168,t:'agent'},
  {n:'"蓝莓" 铅弹',w:'卓越',wv:0,c:189,p:168,t:'agent'},
  {n:'沙哈马特教授 · 精英分子',w:'非凡',wv:0,c:79,p:69.9,t:'agent'},
  {n:'沙哈马特教授 · 精英分子',w:'非凡',wv:0,c:72,p:69.9,t:'agent'},
  {n:'沙哈马特教授 · 精英分子',w:'非凡',wv:0,c:70,p:69.9,t:'agent'},
  {n:'沙哈马特教授 · 精英分子',w:'非凡',wv:0,c:66,p:69.9,t:'agent'},
  {n:'沙哈马特教授 · 精英分子',w:'非凡',wv:0,c:62.8,p:69.9,t:'agent'},

  {n:'NAVI · 2024上海（全息）',w:'Holo',wv:0,c:51,p:31.8,q:3,t:'sticker'},
  {n:'FaZe Clan · 2024上海（全息）',w:'Holo',wv:0,c:49,p:41.9,q:6,t:'sticker'},
  {n:'paiN Gaming · 2021斯德哥尔摩（全息）',w:'Holo',wv:0,c:103,p:79.57,q:1,t:'sticker'},
  {n:'NAVI · 2021斯德哥尔摩（全息）',w:'Holo',wv:0,c:41.5,p:37.4,q:2,t:'sticker'},
  {n:'HEROIC · 2024上海（全息）',w:'Holo',wv:0,c:30.5,p:39.99,q:4,t:'sticker'},
  {n:'EG · 2021斯德哥尔摩（全息）',w:'Holo',wv:0,c:61,p:52.8,q:1,t:'sticker'},
  {n:'NiP · 2021斯德哥尔摩（全息）',w:'Holo',wv:0,c:46.5,p:42.3,q:1,t:'sticker'},
  {n:'MIBR · 2025布达佩斯（全息）',w:'Holo',wv:0,c:31,p:26.78,q:1,t:'sticker'},
  {n:'GamerLegion · 2025布达佩斯（全息）',w:'Holo',wv:0,c:30,p:27.7,q:2,t:'sticker'},
  {n:'Fnatic · 2025布达佩斯（全息）',w:'Holo',wv:0,c:28.4,p:29.7,q:2,t:'sticker'},
  {n:'GamerLegion · 2025布达佩斯（全息）',w:'Holo',wv:0,c:27.6,p:27.7,q:1,t:'sticker'},
  {n:'Complexity · 2022安特卫普（全息）',w:'Holo',wv:0,c:49.8,p:50,q:1,t:'sticker'},
  {n:'iM · 2024上海',w:'普通',wv:0,c:.02,p:.02,q:1,t:'sticker'},

  {n:'DRYDEN · 触摸能量',w:'高级',wv:0,c:10.78,p:11.2,q:1,t:'music'},
];

// derive
H.forEach(h=>{
  const q=h.q||1;
  h.totalCost=h.c*q; h.totalPrice=h.p*q;
  h.pnl=h.totalPrice-h.totalCost;
  h.pnlPct=h.totalCost>0?(h.pnl/h.totalCost*100):0;
  h.wearStr=h.wv>0?h.wv.toFixed(4):'';
  h.qtyStr=q>1?`×${q}`:'';
});

// ═══════════════ CATEGORIES ═══════════════
const CATS=[
  {key:'all',label:'全部',icon:'📊'},
  {key:'weapon',label:'武器',icon:'🔫'},
  {key:'agent',label:'角色手套',icon:'🎭'},
  {key:'sticker',label:'印花',icon:'🏷️'},
  {key:'music',label:'音乐盒',icon:'🎵'},
];

const CAT_META={
  weapon:{color:'var(--blue)',hex:'#3b82f6',label:'武器'},
  agent:{color:'var(--violet)',hex:'#8b5cf6',label:'角色手套'},
  sticker:{color:'var(--amber)',hex:'#f59e0b',label:'印花'},
  music:{color:'var(--cyan)',hex:'#06b6d4',label:'音乐盒'},
};

function summarize(items){
  const tc=items.reduce((s,h)=>s+h.totalCost,0);
  const tp=items.reduce((s,h)=>s+h.totalPrice,0);
  return{cost:tc,value:tp,pnl:tp-tc,pnlPct:tc>0?((tp-tc)/tc*100):0,count:items.length,
    wins:items.filter(h=>h.pnl>0).length,
    maxPnl:items.reduce((m,h)=>h.pnl>m.pnl?h:m,{pnl:-Infinity}),
    maxLoss:items.reduce((m,h)=>h.pnl<m.pnl?h:m,{pnl:Infinity})};
}

const allSummary=summarize(H);

// ═══════════════ KPI ═══════════════
const fmt=v=>'¥'+v.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const fmtI=v=>'¥'+v.toLocaleString('zh-CN',{minimumFractionDigits:0,maximumFractionDigits:0});

document.getElementById('kpiValue').textContent=fmtI(allSummary.value);
document.getElementById('kpiCount').textContent=H.length+' 件藏品';

const kpiPnlEl=document.getElementById('kpiPnl');
kpiPnlEl.textContent=(allSummary.pnl>=0?'+':'')+fmtI(allSummary.pnl);
kpiPnlEl.className='value '+(allSummary.pnl>0?'rise':allSummary.pnl<0?'fall':'');

document.getElementById('kpiPnlPct').textContent=
  `${allSummary.pnl>=0?'+':''}${allSummary.pnlPct.toFixed(2)}% · 胜率 ${Math.round(allSummary.wins/H.length*100)}%`;
document.getElementById('kpiArrow').textContent=allSummary.pnl>=0?'▲':'▼';
document.getElementById('kpiArrow').style.color=allSummary.pnl>=0?'var(--rise)':'var(--fall)';
document.getElementById('kpiCost').textContent=fmtI(allSummary.cost);

// ═══════════════ SECTORS ═══════════════
const sectorGrid=document.getElementById('sectorGrid');
Object.keys(CAT_META).forEach(key=>{
  const items=H.filter(h=>h.t===key);
  const s=summarize(items);
  const m=CAT_META[key];
  const pct=Math.abs(s.pnlPct);
  const maxPct=Math.max(15,pct);
  sectorGrid.innerHTML+=`
    <div class="sector">
      <div class="head"><span class="name">${m.label}</span><span class="count">${s.count}件</span></div>
      <div class="pnl ${s.pnl>=0?'clr-rise':'clr-fall'}">${s.pnl>=0?'+':''}${fmtI(s.pnl)}</div>
      <div class="detail">成本 ${fmtI(s.cost)} · ${s.pnl>=0?'+':''}${s.pnlPct.toFixed(1)}%</div>
      <div class="bar"><div class="bar-fill ${s.pnl>=0?'bar-rise':'bar-fall'}" style="width:${Math.min(pct/maxPct*100,100)}%"></div></div>
    </div>`;
});

// ═══════════════ TABS ═══════════════
let curCat='all',curSort=null,curDir=-1;

const tabBar=document.getElementById('tabBar');
CATS.forEach(c=>{
  const cnt=c.key==='all'?H.length:H.filter(h=>h.t===c.key).length;
  tabBar.innerHTML+=`<button class="tab ${c.key==='all'?'on':''}" data-cat="${c.key}">${c.icon} ${c.label} ${cnt}</button>`;
});
tabBar.addEventListener('click',e=>{
  if(!e.target.classList.contains('tab'))return;
  tabBar.querySelectorAll('.tab').forEach(b=>b.classList.remove('on'));
  e.target.classList.add('on');
  curCat=e.target.dataset.cat;
  render();
});

// ═══════════════ SORT ═══════════════
document.querySelectorAll('.sort-btn').forEach(th=>{
  th.addEventListener('click',()=>{
    const key=th.dataset.sort;
    if(curSort===key)curDir*=-1;else{curSort=key;curDir=key==='name'?1:-1;}
    render();
  });
});

// ═══════════════ RENDER ═══════════════
function render(){
  const items=curCat==='all'?[...H]:H.filter(h=>h.t===curCat);
  if(curSort){
    items.sort((a,b)=>{
      let va,vb;
      if(curSort==='name'){va=a.n;vb=b.n;return curDir*va.localeCompare(vb,'zh');}
      va=a[curSort];vb=b[curSort];
      return curDir*(va-vb);
    });
  }
  document.getElementById('countBadge').textContent=items.length+'件';

  const tbody=document.getElementById('tbody');
  tbody.innerHTML=items.map(h=>{
    const pc=h.pnl>0?'clr-rise':h.pnl<0?'clr-fall':'clr-flat';
    const sign=h.pnl>=0?'+':'';
    const wearInfo=h.wv>0?`<div class="item-sub mono">${h.wearStr}</div>`:'';
    return`<tr>
      <td>
        <div class="item-name">${h.n}${h.qtyStr?`<span class="qty-tag">${h.qtyStr}</span>`:''}</div>
        ${wearInfo}
      </td>
      <td><span class="wear-tag">${h.w}</span></td>
      <td class="text-r text-mono" style="color:var(--text3)">${fmt(h.totalCost)}</td>
      <td class="text-r text-mono" style="color:var(--text)">${fmt(h.totalPrice)}</td>
      <td class="text-r"><span class="${pc}" style="font-weight:700">${sign}${fmt(h.pnl)}</span></td>
      <td class="text-r"><span class="${pc}" style="font-weight:500">${sign}${h.pnlPct.toFixed(1)}%</span></td>
    </tr>`;
  }).join('');
}
render();

// ═══════════════ CHARTS ═══════════════
const chartFont={color:'#52525b',family:"'DM Mono','Noto Sans SC',sans-serif"};
Chart.defaults.color='#52525b';
Chart.defaults.font.family=chartFont.family;
Chart.defaults.font.size=11;

const gridColor='#1e2130';

// Doughnut
new Chart(document.getElementById('doughnut'),{
  type:'doughnut',
  data:{
    labels:Object.values(CAT_META).map(m=>m.label),
    datasets:[{
      data:Object.keys(CAT_META).map(k=>summarize(H.filter(h=>h.t===k)).cost),
      backgroundColor:['rgba(59,130,246,.15)','rgba(139,92,246,.15)','rgba(245,158,11,.15)','rgba(6,182,212,.15)'],
      borderColor:Object.values(CAT_META).map(m=>m.hex),
      borderWidth:2,hoverOffset:6
    }]
  },
  options:{responsive:true,cutout:'65%',
    plugins:{legend:{position:'right',labels:{padding:14,usePointStyle:true,pointStyleWidth:8,font:{size:11}}}}
  }
});

// Bar
const barKeys=Object.keys(CAT_META);
new Chart(document.getElementById('bar'),{
  type:'bar',
  data:{
    labels:barKeys.map(k=>CAT_META[k].label),
    datasets:[
      {label:'成本',data:barKeys.map(k=>summarize(H.filter(h=>h.t===k)).cost),
        backgroundColor:'rgba(59,130,246,.3)',borderColor:'#3b82f6',borderWidth:1,borderRadius:4},
      {label:'现值',data:barKeys.map(k=>summarize(H.filter(h=>h.t===k)).value),
        backgroundColor:barKeys.map(k=>{const s=summarize(H.filter(h=>h.t===k));return s.pnl>=0?'rgba(239,68,68,.3)':'rgba(34,197,94,.3)'}),
        borderColor:barKeys.map(k=>{const s=summarize(H.filter(h=>h.t===k));return s.pnl>=0?'#ef4444':'#22c55e'}),
        borderWidth:1,borderRadius:4}
    ]
  },
  options:{responsive:true,
    plugins:{legend:{labels:{usePointStyle:true,pointStyleWidth:8,font:{size:11}}}},
    scales:{x:{ticks:{font:{size:10}},grid:{display:false}},y:{ticks:{font:{size:10}},grid:{color:gridColor}}}}
});

// Top15
const top15=[...H].sort((a,b)=>b.totalCost-a.totalCost).slice(0,15);
new Chart(document.getElementById('top15'),{
  type:'bar',
  data:{
    labels:top15.map(h=>h.n.replace(/ · /,' ').slice(0,18)),
    datasets:[
      {label:'成本',data:top15.map(h=>h.totalCost),backgroundColor:'rgba(59,130,246,.35)',borderColor:'#3b82f6',borderWidth:1,borderRadius:3},
      {label:'现值',data:top15.map(h=>h.totalPrice),
        backgroundColor:top15.map(h=>h.pnl>=0?'rgba(239,68,68,.35)':'rgba(34,197,94,.35)'),
        borderColor:top15.map(h=>h.pnl>=0?'#ef4444':'#22c55e'),borderWidth:1,borderRadius:3}
    ]
  },
  options:{indexAxis:'y',responsive:true,
    plugins:{legend:{labels:{usePointStyle:true,pointStyleWidth:8,font:{size:10}}}},
    scales:{x:{ticks:{font:{size:9}},grid:{color:gridColor}},y:{ticks:{font:{size:9}},grid:{display:false}}}}
});

// ═══════════════ REFRESH ═══════════════
document.getElementById('refreshBtn').addEventListener('click',()=>{
  const btn=document.getElementById('refreshBtn');
  btn.classList.add('spinning');
  document.querySelector('.container').style.opacity='.4';
  setTimeout(()=>location.reload(),500);
});

// ═══════════════ MARKET INDEX (ECharts) ═══════════════
(async()=>{
  try{
    const r=await fetch('market.json');
    const D=await r.json();
    renderMarket(D);
  }catch(e){
    console.warn('market.json load failed',e);
    document.getElementById('marketSection').style.display='none';
  }
})();

function renderMarket(D){
  const idx=D.index;
  const clr=idx.change>=0?'var(--rise)':'var(--fall)';
  const sign=idx.change>=0?'+':'';
  document.getElementById('miNum').textContent=idx.latest.toFixed(2);
  document.getElementById('miNum').style.color=clr;
  document.getElementById('miChg').textContent=`${sign}${idx.change.toFixed(2)}%`;
  document.getElementById('miChg').style.color=clr;

  // Index line chart
  const ec=echarts.init(document.getElementById('indexChart'),null,{renderer:'canvas'});
  ec.setOption({
    backgroundColor:'transparent',
    grid:{top:10,right:50,bottom:25,left:50},
    xAxis:{type:'category',data:idx.dates,axisLine:{lineStyle:{color:'#252a36'}},axisLabel:{color:'#52525b',fontSize:10,interval:6},axisTick:{show:false}},
    yAxis:{type:'value',min:Math.floor(idx.min.value*0.995),max:Math.ceil(idx.max.value*1.005),splitLine:{lineStyle:{color:'#1e2130'}},axisLabel:{color:'#52525b',fontSize:10}},
    tooltip:{trigger:'axis',backgroundColor:'#1a1e28',borderColor:'#252a36',textStyle:{color:'#e4e4e7',fontSize:12},
      formatter:function(p){const v=p[0];const c=v.value>=(v.dataIndex>0?idx.values[v.dataIndex-1]:v.value)?'var(--rise)':'var(--fall)';return`<b>${v.name}</b><br/><span style="color:${c};font-weight:700">${v.value.toFixed(2)}</span>`}},
    series:[{type:'line',data:idx.values,symbol:'none',lineStyle:{color:'#3b82f6',width:2},
      areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(59,130,246,0.15)'},{offset:1,color:'rgba(59,130,246,0)'}])},
      markLine:{silent:true,symbol:'none',lineStyle:{color:'#2a2d38',type:'dashed'},data:[{yAxis:1000,label:{formatter:'基线 1000',color:'#52525b',fontSize:10}}]},
      markPoint:{data:[{type:'max',name:'高',symbol:'pin',symbolSize:32,itemStyle:{color:'#ef4444'},label:{color:'#fff',fontSize:9,formatter:function(p){return p.value.toFixed(0)}}},{type:'min',name:'低',symbol:'pin',symbolSize:32,itemStyle:{color:'#22c55e'},label:{color:'#fff',fontSize:9,formatter:function(p){return p.value.toFixed(0)}}}]}
    }]}
    ]});

  // K-line chart for selected item
  const itemNames=Object.keys(D.items);
  const defaultItem=itemNames[0];
  const klineEc=echarts.init(document.getElementById('klineChart'),null,{renderer:'canvas'});

  function renderKline(name){
    const item=D.items[name];
    if(!item)return;
    const kl=item.kline;
    const dates=kl.map(k=>{const d=new Date(k[0]*1000);return(d.getMonth()+1)+'-'+d.getDate()});
    const ohlc=kl.map(k=>[k[1],k[2],k[3],k[4]]); // open,close,high,low
    klineEc.setOption({
      backgroundColor:'transparent',
      grid:{top:15,right:50,bottom:30,left:60},
      xAxis:{type:'category',data:dates,axisLine:{lineStyle:{color:'#252a36'}},axisLabel:{color:'#52525b',fontSize:9,interval:8},axisTick:{show:false}},
      yAxis:{type:'value',scale:true,splitLine:{lineStyle:{color:'#1e2130'}},axisLabel:{color:'#52525b',fontSize:9}},
      tooltip:{trigger:'axis',backgroundColor:'#1a1e28',borderColor:'#252a36',textStyle:{color:'#e4e4e7',fontSize:11},
        formatter:function(p){const d=p[0];return`<b>${d.name}</b><br/>开 ${d.data[1]}<br/>收 <span style="color:${d.data[1]>d.data[2]?'var(--fall)':'var(--rise)'};font-weight:700">${d.data[2]}</span><br/>高 ${d.data[3]}<br/>低 ${d.data[4]}`}},
      series:[{type:'candlestick',data:ohlc,itemStyle:{color:'#ef4444',color0:'#22c55e',borderColor:'#ef4444',borderColor0:'#22c55e'}}]
    },true);
  }
  renderKline(defaultItem);

  // Item selector buttons
  const miItems=document.getElementById('miItems');
  itemNames.forEach((name,i)=>{
    const item=D.items[name];
    const chg=item.change;
    const chgCls=chg>0?'clr-up':chg<0?'clr-dn':'';
    const chgSign=chg>0?'+':'';
    miItems.innerHTML+=`
      <div class="mi-item ${i===0?'mi-item-active':''}" data-name="${name}" style="${i===0?'border-color:var(--blue)':''}">
        <div class="mi-item-name">${name}</div>
        <div class="mi-item-price ${chgCls}">&yen;${item.latest.toFixed(1)}</div>
        <div class="mi-item-chg ${chgCls}">${chgSign}${chg.toFixed(2)}%</div>
      </div>`;
  });
  miItems.addEventListener('click',e=>{
    const card=e.target.closest('.mi-item');
    if(!card)return;
    miItems.querySelectorAll('.mi-item').forEach(c=>c.style.borderColor='var(--border)');
    card.style.borderColor='var(--blue)';
    renderKline(card.dataset.name);
  });
  window.addEventListener('resize',()=>klineEc.resize());
}
