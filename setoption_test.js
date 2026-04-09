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
    },
    ]}
  });