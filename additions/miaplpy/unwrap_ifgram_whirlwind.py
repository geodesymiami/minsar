#!/usr/bin/env python3
############################################################
# Program is part of MiaplPy (MinSAR addition)              #
# Unwrap one interferogram with whirlwind-insar             #
#   https://github.com/scottstanie/whirlwind-insar          #
# Same inputs/outputs as unwrap_ifgram.py (snaphu):         #
#   filt_fine.unw (2-band BIL amp+phase) + .unw.conncomp    #
############################################################

import argparse
import os
import sys
import time


def create_parser():
    p = argparse.ArgumentParser(description='Unwrap an ISCE interferogram using whirlwind-insar')
    p.add_argument('-i', '--ifg', dest='input_ifg', required=True, help='Wrapped complex interferogram (ISCE, with .vrt)')
    p.add_argument('-c', '--coherence', dest='input_cor', required=True, help='Coherence file (single band float32)')
    p.add_argument('-u', '--unwrapped_ifg', dest='unwrapped_ifg', required=True, help='Output unwrapped interferogram')
    p.add_argument('-m', '--mask', dest='unwrap_mask', default=None, help='Mask file (nonzero = valid)')
    p.add_argument('-n', '--nlooks', dest='nlooks', type=float, default=200, help='Effective number of looks')
    # whirlwind options; defaults mirror the snaphu settings used by unwrap_ifgram.py (conf.full)
    p.add_argument('--num-threads', dest='num_threads', type=int, default=1,
                   help='Threads per process (sets WHIRLWIND_NUM_THREADS). Default 1: with the launcher '
                        'many unwraps run per node and OMP_NUM_THREADS is not honored by whirlwind')
    p.add_argument('--min-conncomp-frac', dest='min_conncomp_frac', type=float, default=0.01,
                   help='Minimum connected component size as fraction of all pixels (snaphu MINCONNCOMPFRAC, 0.01)')
    p.add_argument('--max-ncomps', dest='max_ncomps', type=int, default=100,
                   help='Maximum number of connected components (snaphu MAXNCOMPS, 100)')
    p.add_argument('--conncomp-reliability', dest='conncomp_reliability', type=float, default=0.5,
                   help='Connected component conservativeness; higher cuts more (whirlwind default 0.5)')
    p.add_argument('--connect-gaps', dest='connect_gaps', action='store_true',
                   help='Level mask-separated regions directly in the solver')
    p.add_argument('--interpolate', dest='interpolate', action='store_true',
                   help='Interpolate low-coherence pixels before the solve')
    p.add_argument('--downsample', dest='downsample', type=int, default=1,
                   help='Solve on a coherently averaged grid of this factor (noisy scenes)')
    p.add_argument('--rmfilter', dest='remove_filter_flag', action='store_true',
                   help='Remove filtering after unwrap')
    p.add_argument('--two-stage', dest='unwrap_2stage', action='store_true',
                   help='Ignored for whirlwind (its bridge step joins components)')
    # accepted and ignored, so the snaphu argument list can be reused
    for opt in ('--max_discontinuity', '--init_method', '--length', '--width', '--height',
                '--num_tiles', '--earth_radius', '--wavelength'):
        p.add_argument(opt, default=None, help=argparse.SUPPRESS)
    p.add_argument('--tmp', action='store_true', help=argparse.SUPPRESS)
    return p


def read_band(path, band=1):
    from osgeo import gdal
    ds = gdal.Open(path + '.vrt' if os.path.exists(path + '.vrt') else path, gdal.GA_ReadOnly)
    arr = ds.GetRasterBand(band).ReadAsArray()
    del ds
    return arr


def main(iargs=None):
    inps = create_parser().parse_args(iargs)
    time0 = time.time()

    # must be set before whirlwind is imported (thread pool is sized at import)
    os.environ['WHIRLWIND_NUM_THREADS'] = str(inps.num_threads)

    import numpy as np
    import whirlwind
    import isceobj
    from isceobj.Util.ImageUtil import ImageLib as IML

    if inps.unwrap_2stage:
        print('whirlwind: --two-stage is ignored')

    unw_file = inps.unwrapped_ifg
    cc_file = unw_file + '.conncomp'

    if not os.path.exists(cc_file + '.vrt'):
        igram = read_band(inps.input_ifg).astype(np.complex64)
        length, width = igram.shape
        corr = np.nan_to_num(read_band(inps.input_cor).astype(np.float32))
        if corr.shape != igram.shape:
            raise RuntimeError('coherence shape {} != interferogram shape {}'.format(corr.shape, igram.shape))

        mask = (igram != 0) & (corr > 0)
        if inps.unwrap_mask:
            # inverted/mask_unwrap is a headerless byte raster (snaphu BYTEMASKFILE)
            mask &= np.fromfile(inps.unwrap_mask, dtype=np.uint8).reshape(length, width) != 0

        print('whirlwind {}: unwrapping {} ({} x {}), nlooks={}'.format(
            whirlwind.__version__, os.path.basename(os.path.dirname(unw_file)), length, width, inps.nlooks))
        min_size_px = max(1, int(round(inps.min_conncomp_frac * length * width)))
        print('whirlwind options: threads={} min_size_px={} max_ncomps={} conncomp_reliability={} '
              'connect_gaps={} interpolate={} downsample={}'.format(
                  inps.num_threads, min_size_px, inps.max_ncomps, inps.conncomp_reliability,
                  inps.connect_gaps, inps.interpolate, inps.downsample))
        unw, conncomp = whirlwind.unwrap(igram, corr, float(inps.nlooks), mask=mask,
                                         min_size_px=min_size_px, max_ncomps=inps.max_ncomps,
                                         conncomp_reliability=inps.conncomp_reliability,
                                         connect_gaps=inps.connect_gaps, interpolate=inps.interpolate,
                                         downsample=inps.downsample)

        out = np.zeros((length, 2, width), dtype=np.float32)   # BIL: amp, phase
        out[:, 0, :] = np.abs(igram)
        out[:, 1, :] = np.where(mask, unw, 0)
        out.tofile(unw_file)
        np.clip(conncomp, 0, 255).astype(np.uint8).tofile(cc_file)

        IML.renderISCEXML(unw_file, bands=2, nyy=length, nxx=width, datatype='float32', scheme='BIL')
        IML.renderISCEXML(cc_file, bands=1, nyy=length, nxx=width, datatype='BYTE', scheme='BIL')
        # vrt files, as written for the snaphu output
        unwImage = isceobj.Image.createUnwImage()
        unwImage.load(unw_file + '.xml')
        unwImage.renderVRT()
        ccImage = isceobj.Image.createImage()
        ccImage.load(cc_file + '.xml')
        ccImage.renderVRT()

    if inps.remove_filter_flag and not os.path.exists(unw_file + '.old'):
        from miaplpy.unwrap_ifgram import remove_filter
        input_ifg_nofilter = os.path.join(os.path.dirname(inps.input_ifg), 'fine.int')
        remove_filter(input_ifg_nofilter, inps.input_ifg, unw_file)

    print('Time spent: {} m'.format((time.time() - time0) / 60))


if __name__ == '__main__':
    main(sys.argv[1:])
