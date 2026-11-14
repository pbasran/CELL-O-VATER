"""Explicit grayscale preprocessing for Cellpose 3 training/inference parity.

Preprocess both paths with this function, then pass normalize=False and
channels=[0, 0] to Cellpose. This avoids the installed training API silently
ignoring normalization dictionary options. Never use these images as raw
intensity measurement inputs.
"""
def prepare_grayscale(image, tile_norm_blocksize=128):
    import numpy as np
    from cellpose import transforms
    source = np.asarray(image)
    if source.ndim != 2 or not np.isfinite(source).all():
        raise ValueError('Expected a finite 2D grayscale image')
    if isinstance(tile_norm_blocksize, bool) or not isinstance(tile_norm_blocksize, int) or tile_norm_blocksize < 0:
        raise ValueError('Tile size must be a nonnegative integer')
    # Cellpose normalization can mutate float inputs; always work on a copy.
    channels = transforms.convert_image(source.copy(), channels=[0, 0])
    normalized = transforms.normalize_img(
        channels.copy(), normalize=True, tile_norm_blocksize=tile_norm_blocksize,
        percentile=(1., 99.), axis=-1,
    )
    result = normalized[..., 0].copy()
    if not np.isfinite(result).all():
        raise ValueError('Normalization produced nonfinite values')
    return result
