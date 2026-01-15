#!/usr/bin/env python3

import isce
from isceobj.Sensor import createSensor
from isceobj.Scene.Track import Track
import shelve
import argparse
import glob
from isceobj.Util import Poly1D
from isceobj.Planet.AstronomicalHandbook import Const
import os
import datetime
import numpy as np

def cmdLineParse():
    '''
    Command line parser.
    '''

    parser = argparse.ArgumentParser(description='Unpack Envisat SLC data and store metadata in pickle file.')
    parser.add_argument('-i','--input', dest='h5dir', type=str,
            required=True, help='Input Envisat directory')
    parser.add_argument('-o', '--output', dest='slcdir', type=str,
            required=True, help='Output SLC directory')

    return parser.parse_args()


def unpack(hdf5, slcname):
    '''
    Unpack multiple HDF5 frames to a single concatenated binary SLC file.
    '''

    # Get all .N1 files (sorted to ensure proper ordering)
    fnames = sorted(glob.glob(os.path.join(hdf5,'ASA*.N1')))
    
    if len(fnames) == 0:
        raise Exception(f'No ASA*.N1 files found in {hdf5}')
    
    print(f'Found {len(fnames)} Envisat frame(s) to process:')
    for fname in fnames:
        print(f'  - {os.path.basename(fname)}')
    
    if not os.path.isdir(slcname):
        os.mkdir(slcname)

    date = os.path.basename(slcname)

    # If only one frame, process it directly
    if len(fnames) == 1:
        print('Single frame - processing without concatenation')
        obj = createSensor('ENVISAT_SLC')
        obj._imageFileName = fnames[0]
        obj.instrumentDir = os.getenv('INS_DIR')
        obj.orbitDir = os.getenv('VOR_DIR')
        obj.output = os.path.join(slcname, date+'.slc')

        obj.extractImage()
        obj.frame.getImage().renderHdr()

        # Force a zero Doppler polynomial so downstream cropFrame.py doesn't choke (FA 1/2026)
        obj.frame._dopplerVsRange = [0.0]
        obj.frame.dopplerVsRange = [0.0]
        obj.frame._dopplerVsPixel = [0.0]

        ######Numpy polynomial manipulation
        #pc = obj._dopplerCoeffs[::-1]
        pc = obj.dopplerRangeTime [:: - 1]        #FA 1/2026: suggested by https://github.com/isce-framework/isce2/discussions/488#discussioncomment-3020238
        
        inds = np.linspace(0, obj.frame.numberOfSamples-1, len(pc) + 1)+1
        rng = obj.frame.getStartingRange() + inds * obj.frame.instrument.getRangePixelSize()
        #dops = np.polyval(pc, 2*rng/Const.c-obj._dopplerTime)       # FA 1/2026
        dops = np.polyval (pc, 2 * rng / Const.c-obj.rangeRefTime)

        print('Near range doppler: ', dops[0])
        print('Far range doppler: ', dops[-1])
       
        dopfit = np.polyfit(inds, dops, len(pc)-1)
        
        poly = Poly1D.Poly1D()
        poly.initPoly(order=len(pc)-1)
        poly.setCoeffs(dopfit[::-1])

        print('Poly near range doppler: ', poly(1))
        print('Poly far range doppler: ', poly(obj.frame.numberOfSamples))

        pickName = os.path.join(slcname, 'data')
        with shelve.open(pickName) as db:
            db['frame'] = obj.frame
            db['doppler'] = poly
        
        return

    # Multiple frames - need to concatenate
    print('Multiple frames detected - concatenating...')
    
    # Create Track object for concatenation
    track = Track()
    track.configure()
    
    temp_outputs = []
    frames = []
    
    # Process each frame
    for i, fname in enumerate(fnames):
        print(f'\nProcessing frame {i+1}/{len(fnames)}: {os.path.basename(fname)}')
        
        obj = createSensor('ENVISAT_SLC')
        obj._imageFileName = fname
        obj.instrumentDir = os.getenv('INS_DIR')
        obj.orbitDir = os.getenv('VOR_DIR')
        
        # Extract to temporary file
        temp_output = os.path.join(slcname, f'temp_frame_{i}.slc')
        obj.output = temp_output
        
        obj.extractImage()
        
        # Force zero Doppler
        obj.frame._dopplerVsRange = [0.0]
        obj.frame.dopplerVsRange = [0.0]
        obj.frame._dopplerVsPixel = [0.0]
        
        frames.append(obj.frame)
        temp_outputs.append(temp_output)
        track.addFrame(obj.frame)
    
    # Stitch frames together
    output_file = os.path.join(slcname, date+'.slc')
    print(f'\nStitching {len(frames)} frames into {output_file}')
    track.stitchFrames(output_file)
    
    # Clean up temporary files
    for temp_file in temp_outputs:
        if os.path.exists(temp_file):
            os.remove(temp_file)
            vrt_file = temp_file + '.vrt'
            hdr_file = temp_file + '.hdr'
            if os.path.exists(vrt_file):
                os.remove(vrt_file)
            if os.path.exists(hdr_file):
                os.remove(hdr_file)
            print(f'Cleaned up: {temp_file}')
    
    # Render header
    track.getFrame().getImage().renderHdr()
    
    # Save concatenated frame to shelve
    pickName = os.path.join(slcname, 'data')
    with shelve.open(pickName) as db:
        db['frame'] = track.getFrame()
    
    print('\nConcatenation complete!')
    print(f'Total lines: {track.getFrame().getNumberOfLines()}')
    print(f'Total samples: {track.getFrame().getNumberOfSamples()}') 


if __name__ == '__main__':
    '''
    Main driver.
    '''

    inps = cmdLineParse()
    if inps.slcdir.endswith('/'):
        inps.slcdir = inps.slcdir[:-1]

    if inps.h5dir.endswith('/'):
        inps.h5dir = inps.h5dir[:-1]

    unpack(inps.h5dir, inps.slcdir)
