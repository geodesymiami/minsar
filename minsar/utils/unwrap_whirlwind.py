"""Unwrap one ISCE interferogram with whirlwind-insar (https://github.com/scottstanie/whirlwind-insar).

Used by the ISCE2 stack unwrap steps (topsStack/unwrap.py, alosStack/unwrap_whirlwind.py).
Writes the same files as snaphu: <unw> (2-band BIL float32, amplitude + phase) and <unw>.conncomp (byte).
"""

import os


def read_band(path, band=1):
    from osgeo import gdal
    ds = gdal.Open(path + '.vrt' if os.path.exists(path + '.vrt') else path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError('cannot open {}'.format(path))
    arr = ds.GetRasterBand(band).ReadAsArray()
    del ds
    return arr


def unwrap_isce_ifgram(ifg_file, cor_file, unw_file, nlooks, num_threads=None, min_conncomp_frac=0.01,
                       max_ncomps=20, conncomp_reliability=0.5):
    """Unwrap ifg_file (complex) using cor_file (coherence, band 1) and write unw_file + .conncomp.

    num_threads: None uses OMP_NUM_THREADS (set in the job file), else 1.
    min_conncomp_frac, max_ncomps: as snaphu MINCONNCOMPFRAC and MAXNCOMPS (ISCE uses 20 components).
    """
    if num_threads is None:
        num_threads = os.environ.get('OMP_NUM_THREADS', '1')
    # must be set before whirlwind is imported (thread pool is sized at import)
    os.environ['WHIRLWIND_NUM_THREADS'] = str(num_threads)

    import numpy as np
    import whirlwind
    import isceobj
    from isceobj.Util.ImageUtil import ImageLib as IML

    igram = read_band(ifg_file).astype(np.complex64)
    length, width = igram.shape
    corr = np.nan_to_num(read_band(cor_file).astype(np.float32))
    if corr.shape != igram.shape:
        raise RuntimeError('coherence shape {} != interferogram shape {}'.format(corr.shape, igram.shape))
    mask = (igram != 0) & (corr > 0)

    min_size_px = max(1, int(round(min_conncomp_frac * length * width)))
    print('whirlwind {}: unwrapping {} ({} x {}), nlooks={} threads={} min_size_px={} max_ncomps={} '
          'conncomp_reliability={}'.format(whirlwind.__version__, ifg_file, length, width, nlooks, num_threads,
                                           min_size_px, max_ncomps, conncomp_reliability))
    unw, conncomp = whirlwind.unwrap(igram, corr, float(nlooks), mask=mask, min_size_px=min_size_px,
                                     max_ncomps=max_ncomps, conncomp_reliability=conncomp_reliability)

    cc_file = unw_file + '.conncomp'
    out = np.zeros((length, 2, width), dtype=np.float32)   # BIL: amplitude, phase
    out[:, 0, :] = np.abs(igram)
    out[:, 1, :] = np.where(mask, unw, 0)
    out.tofile(unw_file)
    np.clip(conncomp, 0, 255).astype(np.uint8).tofile(cc_file)

    IML.renderISCEXML(unw_file, bands=2, nyy=length, nxx=width, datatype='float32', scheme='BIL')
    IML.renderISCEXML(cc_file, bands=1, nyy=length, nxx=width, datatype='BYTE', scheme='BIL')
    unwImage = isceobj.Image.createUnwImage()
    unwImage.load(unw_file + '.xml')
    unwImage.renderVRT()
    ccImage = isceobj.Image.createImage()
    ccImage.load(cc_file + '.xml')
    ccImage.renderVRT()
    return unw_file, cc_file
