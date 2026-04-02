#!/usr/bin/env python3

import isce
from isceobj.Sensor import createSensor
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
        os.makedirs(slcname, exist_ok=True)

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
    print('Multiple frames detected - concatenating with overlap handling...')
    
    temp_outputs = []
    frames_data = []
    
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
        
        frames_data.append({
            'frame': obj.frame,
            'file': temp_output,
            'width': obj.frame.getNumberOfSamples(),
            'length': obj.frame.getNumberOfLines(),
            'start_time': obj.frame.getSensingStart(),
            'stop_time': obj.frame.getSensingStop(),
            'prf': obj.frame.getInstrument().getPulseRepetitionFrequency()
        })
        temp_outputs.append(temp_output)
    
    # Compute frame positions accounting for overlaps
    output_file = os.path.join(slcname, date+'.slc')
    print(f'\nComputing frame positions and overlaps...')
    
    # Check frame widths - if different, need to pad to maximum width
    widths = [f['width'] for f in frames_data]
    max_width = max(widths)
    min_width = min(widths)
    
    if len(set(widths)) != 1:
        print(f'WARNING: Frames have different widths: {widths}')
        print(f'Will pad narrower frames to maximum width: {max_width}')
        
        # Pad narrower frames
        for i, fdata in enumerate(frames_data):
            if fdata['width'] < max_width:
                print(f'  Padding frame {i+1} from {fdata["width"]} to {max_width} samples')
                pad_width = max_width - fdata['width']
                
                # Read original file and write padded version
                padded_file = fdata['file'] + '.padded'
                with open(fdata['file'], 'rb') as inf, open(padded_file, 'wb') as outf:
                    for line in range(fdata['length']):
                        # Read line
                        line_data = inf.read(fdata['width'] * 8)
                        # Write line with zero padding on the right
                        outf.write(line_data)
                        outf.write(b'\x00' * (pad_width * 8))
                
                # Update frame data to use padded file
                os.remove(fdata['file'])
                os.rename(padded_file, fdata['file'])
                fdata['width'] = max_width
                fdata['frame'].setNumberOfSamples(max_width)
    
    width = max_width
    prf = frames_data[0]['prf']
    
    # Calculate start line for each frame based on timing
    track_start_time = frames_data[0]['start_time']
    for i, fdata in enumerate(frames_data):
        time_offset = (fdata['start_time'] - track_start_time).total_seconds()
        start_line = int(round(time_offset * prf))
        fdata['start_line'] = start_line
        print(f'  Frame {i+1}: starts at line {start_line}, {fdata["length"]} lines')
    
    # Calculate total output length
    last_frame = frames_data[-1]
    total_length = last_frame['start_line'] + last_frame['length']
    print(f'Total output length: {total_length} lines (accounting for overlaps)')
    
    # Concatenate with overlap handling (last frame wins)
    print(f'Writing concatenated SLC with overlap handling...')
    bytes_per_line = width * 8  # complex64 = 8 bytes per sample
    
    with open(output_file, 'wb') as outf:
        # Initialize output file with zeros
        outf.write(b'\x00' * (bytes_per_line * total_length))
        
        # Write each frame at its correct position (last frame overwrites overlaps)
        for i, fdata in enumerate(frames_data):
            print(f'  Writing frame {i+1} at line {fdata["start_line"]}')
            outf.seek(fdata['start_line'] * bytes_per_line)
            with open(fdata['file'], 'rb') as inf:
                outf.write(inf.read())
    
    # Use the first frame as template and update dimensions
    combined_frame = frames_data[0]['frame']
    combined_frame.setNumberOfLines(total_length)
    combined_frame.setNumberOfSamples(width)
    
    # Update timing info to span all frames
    combined_frame.setSensingStart(frames_data[0]['start_time'])
    combined_frame.setSensingStop(frames_data[-1]['stop_time'])
    
    # Calculate mid time
    start_time = frames_data[0]['start_time']
    stop_time = frames_data[-1]['stop_time']
    time_diff = (stop_time - start_time).total_seconds() / 2.0
    mid_time = start_time + datetime.timedelta(seconds=time_diff)
    combined_frame.setSensingMid(mid_time)
    
    # Update image reference
    from isceobj import createSlcImage
    rawImage = createSlcImage()
    rawImage.setFilename(output_file)
    rawImage.setAccessMode('read')
    rawImage.setByteOrder('l')
    rawImage.setXmin(0)
    rawImage.setXmax(width)
    rawImage.setWidth(width)
    combined_frame.setImage(rawImage)
    
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
    combined_frame.getImage().renderHdr()
    
    # Save concatenated frame to shelve
    pickName = os.path.join(slcname, 'data')
    with shelve.open(pickName) as db:
        db['frame'] = combined_frame
    
    print('\nConcatenation complete!')
    print(f'Total lines: {combined_frame.getNumberOfLines()}')
    print(f'Total samples: {combined_frame.getNumberOfSamples()}') 


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
