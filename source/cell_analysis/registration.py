"""Translation from the central dark fiducial. No cell correspondences are inferred."""
import numpy as np
import cv2


def locate_fiducial(plane):
    h,w=plane.shape
    small=cv2.resize(plane,(max(1,w//4),max(1,h//4)),interpolation=cv2.INTER_AREA)
    sh,sw=small.shape
    lo,hi=np.percentile(small,[1,99])
    gray=np.uint8(np.clip((small-lo)/max(float(hi-lo),1e-6)*255,0,255))
    x0,x1=sw//4,sw*3//4;y0,y1=sh//4,sh*3//4
    central=gray[y0:y1,x0:x1]
    _,binary=cv2.threshold(cv2.GaussianBlur(central,(5,5),0),0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    def candidates_for(binary, offset=(0,0)):
        count,labels,stats,centers=cv2.connectedComponentsWithStats(binary)
        candidates=[]
        for label in range(1,count):
            x,y,cw,ch,area=stats[label]
            if area<sw*sh*.001 or area>sw*sh*.15:continue
            if x==0 or y==0 or x+cw>=binary.shape[1] or y+ch>=binary.shape[0]:continue
            cx,cy=centers[label]+offset
            distance=np.hypot((cx-sw/2)/sw,(cy-sh/2)/sh)
            if distance>.2:continue
            candidates.append((area/(1+10*distance),label,cx,cy))
        candidates.sort(reverse=True)
        if not candidates:return None
        if len(candidates)>1 and candidates[1][0]>.75*candidates[0][0]:
            raise ValueError('Multiple candidate fiducials; registration requires review')
        return candidates[0],labels
    thin_connection_removed=False
    selected=candidates_for(binary,(x0,y0))
    small_mask=np.zeros_like(gray,dtype=np.uint8)
    if selected:
        (_,label,cx,cy),labels=selected
        small_mask[y0:y1,x0:x1][labels==label]=1
    else:
        # Uneven illumination can make Otsu merge the marker into the field edge.
        # Require a stable isolated dark component at two conservative thresholds.
        found=[]
        background=float(np.percentile(central,65))
        for fraction in (.5,.6):
            _,dark=cv2.threshold(cv2.GaussianBlur(gray,(5,5),0),background*fraction,255,cv2.THRESH_BINARY_INV)
            candidate=candidates_for(dark)
            if candidate is None:
                # Separate a narrow strand connecting the marker to the image edge.
                # Apply only to detection; the source plane is never modified.
                thin_connection_removed=True
                dark=cv2.morphologyEx(dark,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)))
                candidate=candidates_for(dark)
            if candidate is None:raise ValueError('No unambiguous central fiducial found; registration requires review')
            found.append(candidate)
        (_,_,ax,ay),_=found[0]
        (_,label,cx,cy),labels=found[1]
        if np.hypot((ax-cx)/sw,(ay-cy)/sh)>.025:
            raise ValueError('Unstable fiducial location; registration requires review')
        small_mask[labels==label]=1
    mask=cv2.resize(small_mask,(w,h),interpolation=cv2.INTER_NEAREST).astype(bool)
    # Fill the circular field of view using its outer contour, including internal dark fiducial.
    field_binary=np.uint8(gray>max(8,np.percentile(central,65)*.25))*255
    contours,_=cv2.findContours(field_binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:raise ValueError('Field of view could not be identified')
    contour=max(contours,key=cv2.contourArea)
    field_small=np.zeros_like(gray);cv2.drawContours(field_small,[cv2.convexHull(contour)],-1,1,cv2.FILLED)
    if field_small.sum()<sw*sh*.3:raise ValueError('Detected field of view is too small')
    field=cv2.resize(field_small,(w,h),interpolation=cv2.INTER_NEAREST)
    field=cv2.erode(field,np.ones((17,17),np.uint8)).astype(bool)
    return {'center_x_px':float(cx*w/sw),'center_y_px':float(cy*h/sh),'fiducial_area_px':int(mask.sum()),'thin_connection_removed_for_detection':thin_connection_removed},mask,field


def align_to_reference(plane,reference_center=None,margin=80):
    found,fiducial,field=locate_fiducial(plane)
    h,w=plane.shape
    if reference_center is None:reference_center=(found['center_x_px'],found['center_y_px'])
    dx=reference_center[0]-found['center_x_px'];dy=reference_center[1]-found['center_y_px']
    if abs(dx)>w*.2 or abs(dy)>h*.2:raise ValueError('Fiducial displacement exceeds 20% of the image; review registration')
    exclusion=cv2.dilate(fiducial.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*margin+1,2*margin+1))).astype(bool)|~field
    matrix=np.float32([[1,0,dx],[0,1,dy]])
    aligned=cv2.warpAffine(plane,matrix,(w,h),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    valid=cv2.warpAffine((~exclusion).astype(np.uint8),matrix,(w,h),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0).astype(bool)
    result={**found,'reference_center_x_px':reference_center[0],'reference_center_y_px':reference_center[1],
        'translation_x_px':dx,'translation_y_px':dy,'source_to_reference_matrix':matrix.tolist(),
        'method':'central_fiducial_translation','coordinate_space':'reference_image_pixels',
        'exclusion_margin_px':margin,'excluded_pixels':int((~valid).sum()),
        'review_status':'unreviewed','limitation':'Translation only. A single fiducial does not establish rotation, scale or cell lineage.'}
    return aligned,valid,result
