"""Exclude a near-black exterior without removing dark structures inside the field."""
import cv2
import numpy as np

def field_mask(plane):
    high=float(np.percentile(plane,95))
    if high<=0:raise ValueError('Image has no usable illuminated field')
    binary=np.uint8(plane>high*.04)
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:raise ValueError('No image field found')
    contour=max(contours,key=cv2.contourArea)
    mask=np.zeros(plane.shape,np.uint8)
    cv2.drawContours(mask,[contour],-1,1,cv2.FILLED)
    fraction=float(mask.mean())
    if fraction<.3:raise ValueError('Illuminated field occupies less than 30%; review required')
    if fraction<.98:
        mask=cv2.erode(mask,np.ones((17,17),np.uint8))
    return mask.astype(bool)
