

// ═══════════════ DATA ═══════════════

let H = []; // Will be loaded from holdings.json

// Category mapping
const CAT_MAP = {
  '冲锋枪': 'weapon',
  '步枪': 'weapon', 
  '手枪': 'weapon',
  '探员': 'agent',
  '印花': 'sticker',
  '音乐盒': 'music'
};

// Wear mapping
const WEAR_MAP = {
  '崭新出厂': 'FN',
  '略有磨损': 'FT',
  '久经沙场': 'MW',
  '破损不堪': 'WW',
  '战痕累累': 'BS'
};

// Load holdings data
async function loadHoldings() {
  try {
    const r = await fetch('holdings.json');
    const D = await r.json();
    
    // Convert to internal format
    H = D.items.map(item => {
      const t = CAT_MAP[item.category] || 'weapon';
      const w = item.wear ? (WEAR_MAP[item.wear] || item.wear) : (t === 'sticker' ? 'Holo' : t === 'agent' ? '大师' : '');
      const q = item.qty || 1;
      const cost = item.costs ? item.costs.reduce((a,b)=>a+b,0) : item.cost * q;
      const price = item.price * q;
      
      return {
        n: item.name,
        w: w,
        wv: item.wear_value || 0,
        c: item.cost,
        p: item.price,
        t: t,
        q: q,
        totalCost: cost,
        totalPrice: price,
        pnl: price - cost,
        pnlPct: cost > 0 ? ((price - cost) / cost * 100) : 0,
        wearStr: item.wear_value ? item.wear_value.toFixed(4) : '',
        qtyStr: q > 1 ? `×${q}` : ''
      };
    });
    
    initDashboard();
  } catch (e) {
    console.error('Failed to load holdings.json', e);
    // Fallback to hardcoded data
    H = [
      {n:'MP7 · 死亡骷髅',w:'FT',wv:0.1146,c:217,p:243.39,t:'weapon'},
      {n:'M4A4 · 都市 DDPAT',w:'FN',wv:0.0649,c:410,p:377.4,t:'weapon'},
      {n:'FN57 · 夜影',w:'FN',wv:0.0576,c:140,p:135.5,t:'weapon'},
    ];
    H.forEach(h => {
      h.totalCost = h.c; h.totalPrice = h.p;
      h.pnl = h.p - h.c;
      h.pnlPct = h.c > 0 ? (h.pnl / h.c * 100) : 0;
      h.wearStr = h.wv > 0 ? h.wv.toFixed(4) : '';
      h.qtyStr = '';
    });
    initDashboard();
  }
}

function initDashboard() {

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

    if(D.update_time){
      const t=new Date(D.update_time);
      document.getElementById('updateTime').textContent=t.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
    }

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

      markPoint:{data:[{type:'max',name:'MAX',symbol:'pin',symbolSize:32,itemStyle:{color:'#ef4444'},label:{color:'#fff',fontSize:9,formatter:function(p){return p.value.toFixed(0)}}},{type:'min',name:'MIN',symbol:'pin',symbolSize:32,itemStyle:{color:'#22c55e'},label:{color:'#fff',fontSize:9,formatter:function(p){return p.value.toFixed(0)}}}]}

    ]}
  });


  /* CHART_BOUNDARY_EC_INDEX_END */
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

} // end initDashboard

// Start loading
loadHoldings();

