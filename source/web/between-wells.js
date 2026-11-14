let betweenData=null,betweenRequest=null,betweenGeneration=0;
function resetBetween(){betweenGeneration++;betweenData=null;document.getElementById('between-section').hidden=true;document.getElementById('between-map').replaceChildren();}
async function setupBetween(data,request){
 betweenRequest=request;const select=document.getElementById('between-feature');select.replaceChildren();
 for(const f of data.feature_names){const o=document.createElement('option');o.value=f;o.textContent=featureNames[f]||f;select.append(o)}
 select.value=data.feature_names.includes('AreaShape_Area')?'AreaShape_Area':data.feature_names[0];
 document.getElementById('between-section').hidden=false;await loadBetween();
}
async function loadBetween(){
 const generation=++betweenGeneration;betweenData=null;
 document.getElementById('density-comparison').replaceChildren();document.getElementById('between-map').replaceChildren();document.getElementById('between-summary').textContent='Calculating between-well comparisons…';document.getElementById('between-pairs').replaceChildren();document.getElementById('between-download').disabled=true;
 try{
  const data=await(await api('/api/between',{...betweenRequest,feature:document.getElementById('between-feature').value})).json();
  if(generation!==betweenGeneration)return;betweenData=data;drawDensity(data.density_comparison);
  for(const [id,values]of [['between-time',[...new Set(data.wells.map(r=>r.timepoint))]],['between-field',[...new Set(data.wells.map(r=>r.field_id))]]]){
   const s=document.getElementById(id),old=s.value;s.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=id==='between-time'?data.wells.find(r=>r.timepoint===v).label:v;s.append(o)}if(values.includes(old))s.value=old;
  }
  document.getElementById('between-notes').textContent=data.notes.join(' ');document.getElementById('between-download').disabled=false;drawBetween();
 }catch(e){if(generation===betweenGeneration)document.getElementById('between-summary').textContent=e.message;}
}
function drawBetween(){
 if(!betweenData)return;
 const time=document.getElementById('between-time').value,field=document.getElementById('between-field').value,metric=document.getElementById('between-value').value;
 const rows=betweenData.wells.filter(r=>r.timepoint===time&&r.field_id===field),g=betweenData.global.find(r=>r.timepoint===time&&r.field_id===field&&r.feature===betweenData.feature);
 const fmt=x=>x==null?'—':Number(x).toPrecision(4);
 document.getElementById('between-summary').textContent=g?`${g.label} · ${g.from_time} to ${g.to_time}. Global Kruskal–Wallis: H = ${fmt(g.H)}; p = ${fmt(g.p)}; adjusted p (q) = ${fmt(g.q)}. ${g.eligible_wells}/${g.total_wells} wells eligible. ${g.reason|| (g.q<.05?'Differences detected among eligible wells.':'Adjusted threshold not met; this does not establish equivalence.')} Global correction: ${betweenData.global_family} tests. Pairwise correction: ${betweenData.pair_family} planned tests.`:'No comparison available.';
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 800');svg.style.width='100%';svg.setAttribute('role','img');svg.setAttribute('aria-label','Between-well plate values at one time point');
 const add=(tag,attrs,text)=>{const el=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);if(text!=null)el.textContent=text;svg.append(el);return el};
 const text=(x,y,t,size=15)=>add('text',{x,y,'pointer-events':'none','text-anchor':'middle','font-size':size,'font-family':'Arial',fill:'#20383b'},t);
 add('rect',{width:1000,height:800,fill:'white'});text(500,30,(featureNames[betweenData.feature]||betweenData.feature),20);text(500,56,`${g?.label||''} · ${metric==='mean'?'Mean':'Median'} of all measured cells · field ${field}`);text(500,78,'Color shows measured value, not statistical significance. Click a well for comparisons.',13);
 const vals=rows.map(r=>r[metric]).filter(v=>v!=null),lo=Math.min(...vals),hi=Math.max(...vals);
 for(let col=0;col<8;col++)text(120+112*col,110,col+1,19);
 for(let row=0;row<6;row++){
  text(32,180+103*row,'ABCDEF'[row],19);
  for(let col=0;col<8;col++){
   const well='ABCDEF'[row]+(col+1),r=rows.find(r=>r.well_id===well),v=r?.[metric],x=120+112*col,y=175+103*row;
   const fraction=hi>lo?(v-lo)/(hi-lo):.5,fill=v==null?'#e1e5e5':`hsl(192,45%,${95-fraction*48}%)`;
   const circle=add('circle',{cx:x,cy:y,r:45,fill,stroke:'#486b70',tabindex:0,role:'button','aria-label':`Compare well ${well}`});
   text(x,y-16,well);text(x,y+5,fmt(v),14);text(x,y+24,r?`n=${r.finite_count}${r.eligible?'':' *'}`:'No image',12);
   const show=()=>showWell(well,rows,g);circle.onclick=show;circle.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}};
  }
 }
 text(500,756,`Light → dark: ${fmt(vals.length?lo:null)} → ${fmt(vals.length?hi:null)}. * Descriptive only: insufficient regions or unsupported measure.`,14);
 text(500,781,'Exploratory image-level comparisons; independent replicate wells are needed for treatment inference.',13);
 document.getElementById('between-map').replaceChildren(svg);document.getElementById('between-pairs').replaceChildren();
 document.getElementById('between-detail').textContent='Click a well for its cell count, measurement summary and comparisons with other wells.';
}
function showWell(well,rows,g){
 const r=rows.find(r=>r.well_id===well),fmt=x=>x==null?'—':Number(x).toPrecision(4);
 const detail=document.getElementById('between-detail');detail.replaceChildren();
 const heading=document.createElement('h3');heading.textContent=`Well ${well} report`;detail.append(heading);
 if(r){
  const count=document.createElement('p'),strong=document.createElement('strong');strong.textContent=`Cells detected: ${r.cell_count}`;count.append(strong);detail.append(count);
  const scope=document.createElement('p');scope.textContent=`${r.label} · Field ${r.field_id}. Count covers the imaged field, not the entire well.`;detail.append(scope);
  detail.append(table(['Measurement','Value'],[
   ['Cells with a valid selected feature',r.finite_count],
   ['Cells without a valid selected feature',r.cell_count-r.finite_count],
   ['Mean',fmt(r.mean)],['Median',fmt(r.median)],['Standard deviation',fmt(r.sd)],
   ['Quartiles',`${fmt(r.q25)}–${fmt(r.q75)}`],['Usable spatial regions',r.blocks]
  ]));
  if(r.reason){const note=document.createElement('p');note.textContent=r.reason;detail.append(note);}
 }else{const note=document.createElement('p');note.textContent='No image available; cell count unknown.';detail.append(note);}

 const pairs=betweenData.pairs.filter(p=>p.timepoint===g.timepoint&&p.field_id===g.field_id&&(p.well_a===well||p.well_b===well)).sort((a,b)=>a.adjusted_p-b.adjusted_p);
 document.getElementById('between-pairs').replaceChildren(table(['Compared with','Other − selected median','Raw p','Adjusted p','Result'],pairs.map(p=>[p.well_a===well?p.well_b:p.well_a,fmt((p.well_a===well?1:-1)*p.median_difference_b_minus_a),fmt(p.p),fmt(p.adjusted_p),p.adjusted_p<.05?'Difference detected':'Threshold not met'])));
}
document.getElementById('between-feature').onchange=loadBetween;
for(const id of ['between-time','between-field','between-value'])document.getElementById(id).onchange=drawBetween;
document.getElementById('between-download').onclick=async()=>{
 const b=document.getElementById('between-download');b.disabled=true;b.textContent='Preparing tables…';
 try{const response=await api('/api/between-download',{...betweenRequest,feature:betweenData.feature});const a=document.createElement('a'),url=URL.createObjectURL(await response.blob());a.href=url;a.download='between-well-statistics.zip';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);}catch(e){document.getElementById('between-detail').textContent=e.message;}finally{b.disabled=false;b.textContent='Download between-well tables';}
};
function drawDensity(data){
 const host=document.getElementById('density-comparison');host.replaceChildren();
 if(!data?.available){host.textContent=data?.reason||'Density comparison unavailable.';return;}
 const fmt=v=>v==null?'—':Number(v).toFixed(2),ns='http://www.w3.org/2000/svg';
 const maximum=Math.max(1,...data.rows.map(r=>r.density??0))*1.12;
 const cohorts=[...new Set(data.rows.map(r=>JSON.stringify([r.timepoint,r.field_id])))];
 for(const key of cohorts){
  const [time,field]=JSON.parse(key),rows=data.rows.filter(r=>r.timepoint===time&&r.field_id===field),groups=data.groups.filter(g=>g.timepoint===time&&g.field_id===field);
  const h=document.createElement('h3');h.textContent=rows[0].label+' · field '+field;host.append(h);
  const times=rows.map(r=>r.time).sort(),p=document.createElement('p');p.textContent=`Acquired ${times[0]} to ${times[times.length-1]}. Black bars show group means. All panels use the same vertical scale.`;host.append(p);
  const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 510');svg.setAttribute('role','img');svg.setAttribute('aria-label','Seeding density comparison '+rows[0].label+' field '+field);svg.style.width='100%';
  const add=(tag,attrs,t)=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(t!=null)e.textContent=t;svg.append(e);return e;};
  const text=(x,y,t,size=14)=>add('text',{x,y,'font-family':'Arial','font-size':size,'text-anchor':'middle',fill:'#20383b'},t);
  add('rect',{width:1000,height:510,fill:'white'});text(500,24,'Detected cells per million valid pixels',18);
  const y=v=>420-v/maximum*360;
  for(let tick=0;tick<=5;tick++){const v=maximum*tick/5;add('line',{x1:85,x2:960,y1:y(v),y2:y(v),stroke:'#e0e6e6'});text(45,y(v)+5,fmt(v));}
  [250,300,350,400].forEach((seed,index)=>{
   const x=200+index*225,g=groups.find(g=>g.seeded_cells_per_well===seed),points=rows.filter(r=>r.seeded_cells_per_well===seed).sort((a,b)=>a.well_id.localeCompare(b.well_id));
   text(x,452,seed+' cells/well',16);text(x,477,`${g?.valid_wells??0}/12 wells · mean ${fmt(g?.mean)}`);
   for(const r of points){if(r.density==null)continue;
    const offset=('ABCDEF'.indexOf(r.well_id[0])-2.5)*20+(Number(r.well_id.slice(1))%2? -5:5),cx=x+offset,cy=y(r.density);
    const c=add('circle',{cx,cy,r:5,fill:'#267a8b',stroke:'white',tabindex:0,role:'button','aria-label':`${r.label} ${r.well_id}: ${fmt(r.density)} cells per million valid pixels`});
    const title=document.createElementNS(ns,'title');title.textContent=`${r.well_id}: ${r.cells_in_valid_region} cells / ${r.valid_area_px} valid pixels; density ${fmt(r.density)}`;c.append(title);
    const label=text(cx,cy-9,r.well_id,10);label.setAttribute('pointer-events','none');
    const show=()=>{detail.textContent=`${r.well_id} · seeded ${seed} cells/well · ${r.detected_cells} detected cells, ${r.cells_in_valid_region} inside valid region · ${r.valid_area_px.toLocaleString()} valid pixels · ${fmt(r.density)} cells per million valid pixels.`;};c.onclick=show;c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}};
   }
   if(g?.mean!=null)add('line',{x1:x-65,x2:x+65,y1:y(g.mean),y2:y(g.mean),stroke:'#172f34','stroke-width':3,'pointer-events':'none'});
  });
  host.append(svg);const detail=document.createElement('p');detail.textContent='Select a point for its cell count and valid image area.';host.append(detail);
  host.append(table(['Seeded cells/well','Wells with data','Mean density','Median density','SD between wells'],[250,300,350,400].map(seed=>{const g=groups.find(g=>g.seeded_cells_per_well===seed);return[seed,`${g?.valid_wells??0}/12`,fmt(g?.mean),fmt(g?.median),fmt(g?.sd)]})));
  const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Individual well counts and image areas';details.append(summary,table(['Well','Seeded cells/well','Detected cells','Cells in valid region','Valid pixels','Cells/million pixels','Note'],rows.map(r=>[r.well_id,r.seeded_cells_per_well,r.detected_cells,r.cells_in_valid_region??'—',r.valid_area_px??'—',fmt(r.density),r.reason])));host.append(details);
 }
 const note=document.createElement('p');note.textContent=data.notes.join(' ')+' Layout: '+data.layout_source;host.append(note);
}
