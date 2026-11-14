let plateStats=null,plateSvg=null;
const featureNames={AreaShape_Area:'Cell area (px²)',AreaShape_Perimeter:'Perimeter (px)',AreaShape_Eccentricity:'Eccentricity',Intensity_MeanIntensity_Source:'Mean intensity'};
function setupPlate(stats){
 plateStats=stats;const area=document.getElementById('plate-section');area.hidden=!stats.rows.length;if(!stats.rows.length)return;
 for(const [id,values] of [['plate-feature',stats.features],['plate-time',[...new Set(stats.rows.map(r=>r.comparison))]],['plate-field',[...new Set(stats.rows.map(r=>r.field_id))]]]){
  const select=document.getElementById(id);select.replaceChildren();for(const value of values){let option=document.createElement('option');option.value=value;option.textContent=featureNames[value]||value;select.append(option)}if(id==='plate-feature')select.value='AreaShape_Area';select.onchange=drawPlate;
 }
 document.getElementById('plate-notes').textContent=stats.notes.join(' ');
 document.getElementById('plate-method').textContent=stats.method+' · '+stats.correction+' · '+stats.family_size+' planned tests · q < 0.05';
 drawPlate();
}
function drawPlate(){
 const feature=document.getElementById('plate-feature').value,time=document.getElementById('plate-time').value,field=document.getElementById('plate-field').value;
 const records=plateStats.rows.filter(r=>r.feature===feature&&r.comparison===time&&r.field_id===field);
 const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 850');svg.setAttribute('width','1000');svg.setAttribute('height','850');svg.style.width='100%';svg.style.height='auto';svg.setAttribute('role','img');svg.setAttribute('aria-label','48-well exploratory statistical comparison');
 function add(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text)e.textContent=text;svg.append(e);return e}
 add('rect',{width:1000,height:850,fill:'white'});
 const text=(x,y,t,size=16)=>add('text',{x,y,'font-family':'Arial,sans-serif','font-size':size,fill:'#20383b','pointer-events':'none','text-anchor':'middle'},t);
 text(500,30,(featureNames[feature]||feature)+' · '+time,22);text(500,57,'Exploratory spatial-block comparison · field '+field,15);
 text(500,80,plateStats.correction+' across '+plateStats.family_size+' tests · q < 0.05',14);
 for(let c=0;c<8;c++)text(120+c*112,115,String(c+1),20);
 for(let row=0;row<6;row++){
  text(35,180+row*103,'ABCDEF'[row],20);
  for(let c=0;c<8;c++){
   const well='ABCDEF'[row]+(c+1),r=records.find(r=>r.well_id===well),x=120+c*112,y=175+row*103;
   let fill='#e1e5e5',line='No data';
   if(r?.p!=null){fill=r.q<.05?(r.effect>0?'#eaa05a':'#72b6db'):'#ffffff';line='q '+r.q.toFixed(3)}
   else if(r)line=r.status==='unavailable'?'Not tested':'Insufficient';
   const circle=add('circle',{cx:x,cy:y,r:45,fill,stroke:'#657c80','stroke-width':1.5,tabindex:0});
   text(x,y-16,well,15);text(x,y+4,line,12);text(x,y+23,r?.percent_change!=null?(r.percent_change>0?'+':'')+r.percent_change.toFixed(1)+'%':'—',13);
   const show=()=>{document.getElementById('plate-detail').textContent=r?`${well}: ${r.from_time} → ${r.to_time}. ${r.n_cells_t1??'—'} / ${r.n_cells_t2??'—'} eligible cells; ${r.paired_blocks??0} paired blocks. Mean block-median change: ${r.effect?.toPrecision(4)??'—'}. p: ${r.p??'not tested'}; adjusted p (q): ${r.q??'not tested'}. ${r.reason}`:`${well}: no comparison available.`;};circle.onclick=show;circle.onkeydown=e=>{if(e.key==='Enter'||e.key===' ')show()};
  }
 }
 text(500,765,'Orange: increase with q < 0.05   •   Blue: decrease with q < 0.05',15);
 text(500,788,'White: threshold not met   •   Gray: insufficient or missing data',15);
 text(500,814,'Percent change is based on paired spatial-block medians, not total cell count.',14);
 text(500,836,'Exploratory within-field inference; spatial independence is not established.',13);
 document.getElementById('plate-map').replaceChildren(svg);plateSvg=svg;
 document.getElementById('plate-detail').textContent='Click a well for cell numbers, block numbers, effect size and p-values.';
}
document.getElementById('plate-png').onclick=()=>{
 if(!plateSvg)return;
 const button=document.getElementById('plate-png');button.disabled=true;button.textContent='Preparing image…';
 const clone=plateSvg.cloneNode(true);clone.removeAttribute('style');
 const image=new Image(),url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml'}));
 const finish=()=>{URL.revokeObjectURL(url);button.disabled=false;button.textContent='Download plate image';};
 image.onerror=()=>{finish();document.getElementById('plate-detail').textContent='Image export failed. Please try again.';};
 image.onload=()=>{
  const canvas=document.createElement('canvas');canvas.width=2000;canvas.height=1700;
  canvas.getContext('2d').drawImage(image,0,0,2000,1700);
  const link=document.createElement('a');link.href=canvas.toDataURL('image/png');link.download='48-well-statistical-comparison.png';
  document.body.append(link);link.click();link.remove();finish();
 };image.src=url;
};
