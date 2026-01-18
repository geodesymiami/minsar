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
            'prf': obj.frame.getInstrument().getPulseRepetitionFrequency(),
            'original_index': i  # Track original order for debugging
        })
        temp_outputs.append(temp_output)
    
    # CRITICAL: Sort frames by sensing start time (not filename order!)
    # Filenames may not be in chronological order
    frames_data_unsorted = frames_data.copy()
    frames_data.sort(key=lambda x: x['start_time'])
    
    # Check if sorting changed the order
    if any(frames_data[i]['original_index'] != frames_data_unsorted[i]['original_index'] for i in range(len(frames_data))):
        print('\nWARNING: Frames were NOT in chronological order by filename!')
        print('Reordered frames by sensing start time:')
        for i, fdata in enumerate(frames_data):
            print(f'  Frame {i+1} (was #{fdata["original_index"]+1}): starts at {fdata["start_time"]}')
    
    # Compute frame positions accounting for overlaps
    output_file = os.path.join(slcname, date+'.slc')
    print(f'\nComputing frame positions and overlaps...')
    
    # Print actual sensing times for debugging
    print('\nFrame timing information from metadata:')
    for i, fdata in enumerate(frames_data):
        print(f'  Frame {i+1}:')
        print(f'    Sensing start: {fdata["start_time"]}')
        print(f'    Sensing stop:  {fdata["stop_time"]}')
        duration = (fdata["stop_time"] - fdata["start_time"]).total_seconds()
        print(f'    Duration: {duration:.3f} seconds ({fdata["length"]} lines at PRF={fdata["prf"]:.2f} Hz)')
        expected_lines = duration * fdata["prf"]
        print(f'    Expected lines from timing: {expected_lines:.1f}')
        if abs(expected_lines - fdata["length"]) > 10:
            print(f'    WARNING: Line count mismatch! ({expected_lines:.1f} expected vs {fdata["length"]} actual)')
    
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
    
    # Calculate expected overlap between frames
    print('\nDetecting frame overlaps and gaps...')
    
    # Check gaps/overlaps between consecutive frames
    for i in range(len(frames_data) - 1):
        frame_curr = frames_data[i]
        frame_next = frames_data[i+1]
        
        gap_seconds = (frame_next['start_time'] - frame_curr['stop_time']).total_seconds()
        gap_lines = gap_seconds * prf
        
        print(f'\nBetween frames {i+1} and {i+2}:')
        print(f'  Frame {i+1} ends:   {frame_curr["stop_time"]}')
        print(f'  Frame {i+2} starts: {frame_next["start_time"]}')
        
        if gap_seconds > 0:
            print(f'  → GAP of {gap_seconds:.3f} seconds ({gap_lines:.1f} lines)')
        elif gap_seconds < 0:
            print(f'  → OVERLAP of {-gap_seconds:.3f} seconds ({-gap_lines:.1f} lines)')
        else:
            print(f'  → Perfect continuation (no gap or overlap)')
    
    track_start_time = frames_data[0]['start_time']
    
    # For first frame, calculate expected number of lines from timing
    for i in range(len(frames_data)):
        fdata = frames_data[i]
        
        # Calculate where this frame should start based on timing
        time_offset = (fdata['start_time'] - track_start_time).total_seconds()
        expected_start_line = time_offset * prf
        
        # Calculate expected end time and line
        frame_duration = (fdata['stop_time'] - fdata['start_time']).total_seconds()
        expected_lines_from_timing = frame_duration * prf
        
        print(f'  Frame {i+1}:')
        print(f'    Start time offset: {time_offset:.3f} s → line {expected_start_line:.1f}')
        print(f'    Duration: {frame_duration:.3f} s → {expected_lines_from_timing:.1f} lines')
        print(f'    Actual lines in file: {fdata["length"]}')
        
        # Store for overlap calculation
        fdata['expected_start'] = expected_start_line
        fdata['expected_duration'] = expected_lines_from_timing
    
    # Concatenation: Handle overlaps by splitting removal between frames
    # This minimizes phase discontinuity at frame boundaries
    print('\nConcatenating frames (splitting overlap removal to minimize boundary artifacts)...')
    bytes_per_line = width * 8  # complex64 = 8 bytes per sample
    
    # First pass: calculate how much to trim from end of each frame (except last)
    cumulative_position = 0
    
    for i in range(len(frames_data)):
        fdata = frames_data[i]
        
        # Calculate expected start position based on timing
        time_offset = (fdata['start_time'] - frames_data[0]['start_time']).total_seconds()
        expected_start = time_offset * prf
        
        fdata['expected_start_line'] = expected_start
        fdata['trim_start'] = 0
        fdata['trim_end'] = 0
        
        if i == 0:
            # First frame: no trim_start, might have trim_end
            fdata['output_start'] = 0
            cumulative_position = fdata['length']
        else:
            # Calculate overlap
            overlap = cumulative_position - expected_start
            
            if overlap > 0:
                # Split overlap: trim half from previous frame's end, half from this frame's start
                trim_prev_end = int(overlap // 2)
                trim_curr_start = overlap - trim_prev_end
                
                # Update previous frame
                frames_data[i-1]['trim_end'] = trim_prev_end
                cumulative_position -= trim_prev_end  # Adjust for trimmed lines
                
                # Update current frame
                fdata['trim_start'] = trim_curr_start
                fdata['output_start'] = cumulative_position
                
                print(f'\nBetween frames {i} and {i+1}:')
                print(f'  Overlap: {overlap} lines')
                print(f'  Splitting: trim {trim_prev_end} from end of frame {i}, {trim_curr_start} from start of frame {i+1}')
                print(f'  This centers the boundary at the overlap midpoint')
                
                cumulative_position += (fdata['length'] - trim_curr_start)
            else:
                # No overlap or gap
                fdata['output_start'] = cumulative_position
                cumulative_position += fdata['length']
    
    # Second pass: write the frames with trimming
    print('\nWriting concatenated frames...')
    with open(output_file, 'wb') as outf:
        cumulative_lines = 0
        
        for i, fdata in enumerate(frames_data):
            trim_start = fdata.get('trim_start', 0)
            trim_end = fdata.get('trim_end', 0)
            lines_to_write = fdata['length'] - trim_start - trim_end
            
            print(f'  Frame {i+1}:')
            print(f'    Total lines: {fdata["length"]}')
            if trim_start > 0:
                print(f'    Trimming start: {trim_start} lines')
            if trim_end > 0:
                print(f'    Trimming end: {trim_end} lines')
            print(f'    Writing: {lines_to_write} lines at position {cumulative_lines}')
            
            with open(fdata['file'], 'rb') as inf:
                # Skip trimmed start
                inf.seek(trim_start * bytes_per_line)
                # Read the portion to write
                data_to_write = inf.read(lines_to_write * bytes_per_line)
                outf.write(data_to_write)
            
            fdata['skipped'] = trim_start + trim_end
            cumulative_lines += lines_to_write
    
    # Calculate total lines written (accounting for skipped overlaps)
    total_length = cumulative_lines
    print(f'\nTotal lines written: {total_length}')
    
    # Use the first frame as template and update dimensions
    combined_frame = frames_data[0]['frame']
    combined_frame.setNumberOfLines(total_length)
    combined_frame.setNumberOfSamples(width)
    
    # Update timing info to span all frames
    # Important: The azimuth time grid is now uniform from first to last frame
    # Each line represents a unique azimuth time sample
    combined_frame.setSensingStart(frames_data[0]['start_time'])
    combined_frame.setSensingStop(frames_data[-1]['stop_time'])
    
    # Calculate mid time
    start_time = frames_data[0]['start_time']
    stop_time = frames_data[-1]['stop_time']
    total_duration = (stop_time - start_time).total_seconds()
    time_diff = total_duration / 2.0
    mid_time = start_time + datetime.timedelta(seconds=time_diff)
    combined_frame.setSensingMid(mid_time)
    
    # Verify azimuth time grid consistency
    expected_lines_from_timing = total_duration * prf
    print(f'\nAzimuth time grid verification:')
    print(f'  Total sensing duration: {total_duration:.3f} seconds')
    print(f'  PRF: {prf:.3f} Hz')
    print(f'  Expected lines from timing: {expected_lines_from_timing:.1f}')
    print(f'  Actual lines written: {total_length}')
    line_discrepancy = abs(expected_lines_from_timing - total_length)
    if line_discrepancy > 10:
        print(f'  WARNING: Line count discrepancy of {line_discrepancy:.1f} lines!')
        print(f'           This may indicate timing or PRF issues.')
    else:
        print(f'  ✓ Line count matches expected timing (within {line_discrepancy:.1f} lines)')
    
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
