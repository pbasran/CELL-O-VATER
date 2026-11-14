let timeCourseData=null;
const imageFeatures={cell_count:'Detected cell count',segmented_cell_area_px2:'Total segmented cell area (valid region, px²)',coverage_percent:'Cell coverage (%)'};
function timeNumber(value){
 // Treat recorded local clock times consistently, without assigning a browser timezone.
 const s=String(value);return Date.parse(/[zZ]$|[+-]\d\d:\d\d$/.test(s)?s:s+'Z');
}
function timelineSeries(data,feature,stat,field,rows,cols){
 const cells=new Map();for(const c of data.observations){if(!cells.has(c.image_uid))cells.set(c.image_uid,[]);cells.get(c.image_uid).push(c);}
 const exports=[...new Set(data.images.map(i=>i.export_path))].sort((a,b)=>Math.min(...data.images.filter(i=>i.export_path===a).map(i=>timeNumber(i.time)))-Math.min(...data.images.filter(i=>i.export_path===b).map(i=>timeNumber(i.time))));
 const origin=Math.min(...data.images.map(i=>timeNumber(i.time)).filter(Number.isFinite)),lines=new Map();
 for(const im of data.images){
  const match=/^([A-F])([1-8])$/.exec(im.well_id);if(!match||im.field_id!==field||!rows.includes(match[1])||!cols.includes(match[2]))continue;
  let value=null,n=0;
  if(feature in imageFeatures){value=im[feature]??null;n=feature==='cell_count'?im.cell_count:null;}
  else{const values=(cells.get(im.image_uid)||[]).map(c=>c[feature]).filter(v=>v!==''&&v!==null&&v!==undefined).map(Number).filter(Number.isFinite).sort((a,b)=>a-b);n=values.length;if(n)value=stat==='mean'?values.reduce((a,b)=>a+b,0)/n:(values[Math.floor(n/2)]+values[Math.floor((n-1)/2)])/2;}
  if(!lines.has(im.well_id))lines.set(im.well_id,[]);
  lines.get(im.well_id).push({time:im.time,hours:(timeNumber(im.time)-origin)/3600000,value,n,validArea:im.valid_image_area_px2??null,note:feature!=='cell_count'&&feature in imageFeatures?im.coverage_note||'':'',cells:im.cell_count,exportIndex:exports.indexOf(im.export_path)});
 }
 return {origin,lines:[...lines].sort((a,b)=>a[0].localeCompare(b[0])).map(([well,points])=>({well,points:points.sort((a,b)=>a.hours-b.hours)}))};
}
function resetTimeCourse(){timeCourseData=null;document.getElementById('time-course').hidden=true;}
function setupTimeCourse(data){
 timeCourseData=data;document.getElementById('time-course').hidden=false;
 for(const [id,values]of [['tc-feature',[...Object.keys(imageFeatures),...data.feature_names]],['tc-field',[...new Set(data.images.map(i=>i.field_id))]]]){
  const select=document.getElementById(id);select.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=imageFeatures[v]||featureNames[v]||v;select.append(o)}
 }
 document.getElementById('tc-feature').value=data.feature_names.includes('AreaShape_Area')?'AreaShape_Area':'cell_count';
 for(const [id,values]of [['tc-rows',[...'ABCDEF']],['tc-cols',[...'12345678']]]){
  const host=document.getElementById(id);host.replaceChildren();for(const v of values){const label=document.createElement('label');label.style.cssText='display:inline-block;margin:8px 16px 8px 0';const c=document.createElement('input');c.type='checkbox';c.value=v;c.checked=id==='tc-cols'||v==='A';c.setAttribute('aria-label',(id==='tc-rows'?'Row ':'Column ')+v);c.onchange=drawTimeCourse;label.append(c,' '+v);host.append(label)}
 }
 drawTimeCourse();
}
function drawTimeCourse(){
 if(!timeCourseData)return;
 const read=id=>[...document.getElementById(id).querySelectorAll('input:checked')].map(c=>c.value),feature=document.getElementById('tc-feature').value,stat=document.getElementById('tc-stat').value,field=document.getElementById('tc-field').value;
 document.getElementById('tc-stat').disabled=feature in imageFeatures;
 const result=timelineSeries(timeCourseData,feature,stat,field,read('tc-rows'),read('tc-cols')),host=document.getElementById('tc-plot');host.replaceChildren();document.getElementById('tc-table').replaceChildren();document.getElementById('tc-detail').textContent='Select a point for its acquisition time and cell count.';
 const valid=result.lines.flatMap(l=>l.points).filter(p=>p.value!==null&&Number.isFinite(p.hours));
 if(!valid.length){host.textContent='No measurements for this selection. Select a row and column; coverage also requires matching segmentation and valid-region masks.';return;}
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1100 620');svg.style.width='100%';svg.setAttribute('role','img');svg.setAttribute('aria-label','Selected well features over time');
 const add=(tag,attrs,t)=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(t!=null)e.textContent=t;svg.append(e);return e;};
 const text=(x,y,t,size=14)=>add('text',{x,y,'font-size':size,'font-family':'Arial','text-anchor':'middle',fill:'#20383b','pointer-events':'none'},t);
 const name=imageFeatures[feature]||`${stat==='mean'?'Mean':'Median'} ${featureNames[feature]||feature}`;
 add('rect',{width:1100,height:620,fill:'white'});text(550,30,name,21);text(550,56,`Field ${field} · ${result.lines.length} wells · one line per well`);
 let ymin=Math.min(...valid.map(p=>p.value)),ymax=Math.max(...valid.map(p=>p.value));const pad=(ymax-ymin||Math.abs(ymax)||1)*.1;ymin-=pad;ymax+=pad;
 const xmax=Math.max(1,...valid.map(p=>p.hours)),x=h=>105+h/xmax*940,y=v=>515-(v-ymin)/(ymax-ymin)*420,fmt=v=>Number(v).toPrecision(4);
 for(let tick=0;tick<=5;tick++){const v=ymin+(ymax-ymin)*tick/5;add('line',{x1:105,x2:1045,y1:y(v),y2:y(v),stroke:'#e0e6e6'});text(49,y(v)+5,fmt(v));const h=xmax*tick/5;text(x(h),548,h.toFixed(1));}
 text(550,580,'Hours since earliest selected acquisition (not hours since seeding)',16);
 text(550,605,'Recorded local times; timezone uncertainty retained. Lines summarize fields, not tracked individual cells.',13);
 const legend=document.createElement('div');legend.style.cssText='display:flex;flex-wrap:wrap;gap:10px 22px;margin:8px 0';
 for(const line of result.lines){
  const index=('ABCDEF'.indexOf(line.well[0])*8+Number(line.well.slice(1))-1),color=`hsl(${index*137.508%360},65%,35%)`,dash=['','8 4','2 4','10 3 2 3'][index%4];let prev=null;
  for(const p of line.points){if(p.value===null||!Number.isFinite(p.hours)){prev=null;continue;}
   if(prev&&Math.abs(p.exportIndex-prev.exportIndex)===1)add('line',{x1:x(prev.hours),y1:y(prev.value),x2:x(p.hours),y2:y(p.value),stroke:color,'stroke-width':2,'stroke-dasharray':dash});
   const dot=add('circle',{cx:x(p.hours),cy:y(p.value),r:5,fill:color,stroke:'white',tabindex:0,role:'button','aria-label':`${line.well} at ${p.time}`});
   const title=document.createElementNS(ns,'title');title.textContent=`${line.well}: ${fmt(p.value)} at ${p.time}; ${p.cells} detected cells`;dot.append(title);
   const show=()=>document.getElementById('tc-detail').textContent=`${line.well} · ${p.time} · ${p.hours.toFixed(2)} hours · ${name}: ${fmt(p.value)} · ${p.n===null?'Whole-field metric':p.n+' valid measurements'} / ${p.cells} detected cells.${p.validArea===null?'':' Valid image area: '+p.validArea.toLocaleString()+' px².'}`;dot.onclick=show;dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}};prev=p;
  }
  const item=document.createElement('span');item.style.color=color;item.textContent='━ '+line.well;legend.append(item);
 }
 host.append(svg,legend);
 document.getElementById('tc-table').append(table(['Well','Acquired','Elapsed hours','Value','Valid measurements','Detected cells','Valid image area (px²)','Note'],result.lines.flatMap(l=>l.points.map(p=>[l.well,p.time,p.hours.toFixed(2),p.value===null?'Missing':fmt(p.value),p.n??'—',p.cells,p.validArea??'—',p.note]))));
}
if(typeof document!=='undefined'){
 for(const id of ['tc-feature','tc-stat','tc-field'])document.getElementById(id).onchange=drawTimeCourse;
 for(const scope of ['rows','cols'])for(const action of ['all','none'])document.getElementById(`tc-${scope}-${action}`).onclick=()=>{document.getElementById('tc-'+scope).querySelectorAll('input').forEach(c=>c.checked=action==='all');drawTimeCourse();};
}
if(typeof module!=='undefined')module.exports={timelineSeries,timeNumber};
