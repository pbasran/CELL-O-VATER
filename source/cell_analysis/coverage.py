"""Image-level occupancy from instance masks in the same registered image grid."""
from pathlib import Path
import numpy as np
import tifffile


def measure_coverage(folder):
    result={'segmented_cell_area_px2':None,'valid_image_area_px2':None,'coverage_percent':None,'coverage_status':'unavailable','coverage_note':''}
    try:
        folder=Path(folder)
        labels=tifffile.imread(folder/'segmentation_mask.tif')
        region=tifffile.imread(folder/'analysis_region.tif')
        if labels.ndim!=2 or region.ndim!=2 or labels.shape!=region.shape:
            raise ValueError('Segmentation and valid-region masks must have matching 2D dimensions')
        if not np.isfinite(labels).all() or not np.isfinite(region).all() or (labels<0).any() or (region<0).any():
            raise ValueError('Masks contain invalid pixel values')
        valid=region>0;area=int(np.count_nonzero(valid))
        if area==0:raise ValueError('Valid image region is empty')
        occupied=int(np.count_nonzero((labels>0)&valid))
        result.update(segmented_cell_area_px2=occupied,valid_image_area_px2=area,coverage_percent=100*occupied/area,coverage_status='available')
    except (OSError,ValueError) as e:result['coverage_note']=str(e)
    return result
