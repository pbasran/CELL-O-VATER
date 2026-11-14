"""Descriptive density comparison for the confirmed OSCA #2.5 plate layout."""
from collections import defaultdict
from pathlib import Path
import re
import numpy as np
import tifffile


def calculate(analysis):
    ids=analysis.get('dataset_ids',[])
    known=bool(ids) and all('OSCA' in d.upper() and re.search(r'#2\.5(?!\d)',d) for d in ids)
    result={'available':known,'units':'cells per million valid pixels','seeding_units':'cells per well',
            'layout_source':'Well_DensititesTest#2.5.xlsx, OSCA-78s!A1:I7; seeding units confirmed by user as cells/well',
            'rows':[],'groups':[],'notes':[
                'Columns 1–2: 250; 3–4: 300; 5–6: 350; 7–8: 400 cells seeded per well. Twelve wells per group are expected.',
                'Each dot is one well’s imaged field. Density = cells with centroids inside the valid analysis region / valid pixels × 1,000,000. It is not a whole-well count.',
                'Group means and SD weight each well equally. Missing images or masks are not zeros. Raw detected counts are retained separately.',
                'Pixel-based densities require comparable image scale. No physical-area calibration or whole-well extrapolation is applied.',
                'The four groups occupy fixed column pairs, so seeding level and plate position are confounded. This descriptive plot does not establish a treatment effect.'
            ]}
    if not known:
        result['reason']='No confirmed seeding layout for this dataset. The OSCA #2.5 layout is not applied to other experiments.'
        return result
    cells=defaultdict(list)
    for c in analysis['observations']:cells[c['image_uid']].append(c)
    buckets=defaultdict(list)
    for im in analysis['images']:
        well=im['well_id']
        if not re.fullmatch('[A-F][1-8]',well):raise ValueError('Well outside confirmed 48-well layout: '+well)
        seeded=[250,300,350,400][(int(well[1:])-1)//2]
        row={'timepoint':im['export_path'],'label':Path(im['export_path']).name,'time':im['time'],'field_id':im['field_id'],'well_id':well,'seeded_cells_per_well':seeded,'detected_cells':len(cells[im['image_uid']]),'cells_in_valid_region':None,'valid_area_px':None,'density':None,'reason':''}
        try:
            mask=tifffile.imread(Path(im['folder'])/'analysis_region.tif').astype(bool)
            if mask.ndim!=2:raise ValueError('Analysis region must be 2D')
            area=int(mask.sum())
            if area<=0:raise ValueError('Analysis region is empty')
            h,w=mask.shape;n=0
            for c in cells[im['image_uid']]:
                x,y=c['x_reference_px']-im['translation_x_px'],c['y_reference_px']-im['translation_y_px']
                if not np.isfinite([x,y]).all():continue
                ix,iy=round(x),round(y)
                if 0<=ix<w and 0<=iy<h and mask[iy,ix]:n+=1
            row.update(cells_in_valid_region=n,valid_area_px=area,density=n/area*1e6)
        except (OSError,ValueError) as e:row['reason']=str(e)
        result['rows'].append(row);buckets[(row['timepoint'],row['field_id'],seeded)].append(row)
    for (timepoint,field,seeded),rows in sorted(buckets.items()):
        if len({r['well_id'] for r in rows})!=len(rows):raise ValueError('Duplicate well in density group')
        vals=[r['density'] for r in rows if r['density'] is not None]
        result['groups'].append({'timepoint':timepoint,'label':rows[0]['label'],'field_id':field,'seeded_cells_per_well':seeded,'expected_wells':12,'images':len(rows),'valid_wells':len(vals),'mean':float(np.mean(vals)) if vals else None,'median':float(np.median(vals)) if vals else None,'sd':float(np.std(vals,ddof=1)) if len(vals)>1 else None})
    return result
