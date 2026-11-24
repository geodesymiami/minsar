#!/usr/bin/env python3

#
# MinSAR addition: unwrap an alosStack pair with whirlwind-insar.
# Same arguments, working directory and output files as unwrap_snaphu.py
# (steps follow isceobj.Alos2Proc.runUnwrapSnaphu.unwrapSnaphu).
#

import os
import sys
import argparse
import numpy as np

import isce, isceobj
from isceobj.Alos2Proc.Alos2ProcPublic import runCmd

from minsar.utils.unwrap_whirlwind import unwrap_isce_ifgram


def cmdLineParse():
    '''
    command line parser.
    '''
    parser = argparse.ArgumentParser(description='unwrap filtered interferogram using whirlwind')
    parser.add_argument('-idir', dest='idir', type=str, required=True,
            help = 'input directory where resampled data of each date (YYMMDD) is located. only folders are recognized')
    parser.add_argument('-ref_date_stack', dest='ref_date_stack', type=str, required=True,
            help = 'reference date of stack. format: YYMMDD')
    parser.add_argument('-ref_date', dest='ref_date', type=str, required=True,
            help = 'reference date of this pair. format: YYMMDD')
    parser.add_argument('-sec_date', dest='sec_date', type=str, required=True,
            help = 'reference date of this pair. format: YYMMDD')
    parser.add_argument('-nrlks1', dest='nrlks1', type=int, default=1,
            help = 'number of range looks 1. default: 1')
    parser.add_argument('-nalks1', dest='nalks1', type=int, default=1,
            help = 'number of azimuth looks 1. default: 1')
    parser.add_argument('-nrlks2', dest='nrlks2', type=int, default=1,
            help = 'number of range looks 2. default: 1')
    parser.add_argument('-nalks2', dest='nalks2', type=int, default=1,
            help = 'number of azimuth looks 2. default: 1')
    parser.add_argument('-wbd_msk', dest='wbd_msk', action='store_true', default=False,
            help='mask unwrapped interferogram with water body')
    parser.add_argument('-nlooks', dest='nlooks', type=float, default=None,
            help = 'effective number of looks for whirlwind. default: range looks x azimuth looks')

    if len(sys.argv) <= 1:
        print('')
        parser.print_help()
        sys.exit(1)
    else:
        return parser.parse_args()


if __name__ == '__main__':

    inps = cmdLineParse()

    nrlks = inps.nrlks1 * inps.nrlks2
    nalks = inps.nalks1 * inps.nalks2
    pair = '{}-{}'.format(inps.ref_date, inps.sec_date)
    ml2 = '_{}rlks_{}alks'.format(nrlks, nalks)

    filteredInterferogram = 'filt_' + pair + ml2 + '.int'
    multilookPhsig = pair + ml2 + '.phsig'
    unwrappedInterferogram = 'filt_' + pair + ml2 + '.unw'
    unwrappedMaskedInterferogram = 'filt_' + pair + ml2 + '_msk.unw'
    multilookWbdOut = os.path.join('../', inps.idir, inps.ref_date_stack, 'insar', inps.ref_date_stack + ml2 + '.wbd')

    insarDir = 'insar'
    os.makedirs(insarDir, exist_ok=True)
    os.chdir(insarDir)

    # STEP 1. unwrap interferogram
    nlooks = inps.nlooks if inps.nlooks is not None else nrlks * nalks
    unwrap_isce_ifgram(filteredInterferogram, multilookPhsig, unwrappedInterferogram, nlooks)

    # STEP 2. mask using connected components
    cmd = "imageMath.py -e='a_0*(b>0);a_1*(b>0)' --a={} --b={} -s BIL -t float -o={}".format(
        unwrappedInterferogram, unwrappedInterferogram+'.conncomp', unwrappedMaskedInterferogram)
    runCmd(cmd)

    # STEP 3. mask using water body
    if inps.wbd_msk:
        wbdImage = isceobj.createImage()
        wbdImage.load(multilookWbdOut+'.xml')
        width = wbdImage.width
        length = wbdImage.length
        wbd = np.fromfile(multilookWbdOut, dtype=np.int8).reshape(length, width)
        for name in (unwrappedInterferogram, unwrappedMaskedInterferogram):
            unw = np.memmap(name, dtype='float32', mode='r+', shape=(length*2, width))
            (unw[0:length*2:2, :])[np.nonzero(wbd==-1)]=0
            (unw[1:length*2:2, :])[np.nonzero(wbd==-1)]=0
            del unw
        del wbd

    os.chdir('../')
