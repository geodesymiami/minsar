import glob
import h5py
import numpy as np
import os

def get_flight_direction(fname):
    """Extract flight direction from HDF5/HDFEOS file.
    
    Based on MintPy's info.py approach for reading attributes.
    
    Parameters:
    -----------
    fname : str
        Path to HDF5/HDFEOS file (.h5 or .he5)
    
    Returns:
    --------
    str
        Flight direction: 'asc' for ascending or 'desc' for descending
        Returns None if neither ORBIT_DIRECTION nor flight_direction is found
    
    Notes:
    ------
    - First tries to read ORBIT_DIRECTION attribute
    - Falls back to flight_direction attribute if ORBIT_DIRECTION not found
    - Maps: ASCENDING/A -> 'asc', DESCENDING/D -> 'desc'
    """
    fname = os.fspath(fname)  # Convert from possible pathlib.Path
    
    if not os.path.isfile(fname):
        raise FileNotFoundError(f'Input file does not exist: {fname}')
    
    fext = os.path.splitext(fname)[1].lower()
    if fext not in ['.h5', '.he5']:
        raise ValueError(f'Input file must be HDF5/HDFEOS format (.h5 or .he5): {fname}')
    
    # Read attributes from file (similar to MintPy's read_attribute)
    # Try root level first, then check groups/datasets if needed
    with h5py.File(fname, 'r') as f:
        # Check root level attributes first
        root_atr = dict(f.attrs)
        
        # Decode string format (like MintPy does)
        for key, value in root_atr.items():
            try:
                root_atr[key] = value.decode('utf8')
            except:
                root_atr[key] = value
        
        # Try to find ORBIT_DIRECTION or flight_direction in root attributes first
        if 'ORBIT_DIRECTION' in root_atr or 'flight_direction' in root_atr:
            atr = root_atr
        # If not in root and WIDTH exists, use root attributes
        elif len(root_atr) > 0 and 'WIDTH' in root_atr.keys():
            atr = root_atr
        else:
            # Look for attributes in groups/datasets (HDFEOS structure)
            global atr_list
            
            def get_hdf5_attrs(name, obj):
                global atr_list
                if len(obj.attrs) > 0:
                    # Prefer attributes with WIDTH, but also collect any with our target attributes
                    if 'WIDTH' in obj.attrs.keys() or 'ORBIT_DIRECTION' in obj.attrs.keys() or 'flight_direction' in obj.attrs.keys():
                        atr_list.append(dict(obj.attrs))
            
            atr_list = []
            f.visititems(get_hdf5_attrs)
            
            # Prioritize attributes with ORBIT_DIRECTION or flight_direction
            priority_atr = None
            for a in atr_list:
                if 'ORBIT_DIRECTION' in a or 'flight_direction' in a:
                    priority_atr = a
                    break
            
            if priority_atr:
                atr = priority_atr
            # Otherwise, use the attrs with most items
            elif atr_list:
                num_list = [len(i) for i in atr_list]
                atr = atr_list[np.argmax(num_list)]
            else:
                # Fall back to root attributes even if empty
                atr = root_atr
        
        # Decode string format for all attributes
        for key, value in atr.items():
            try:
                atr[key] = value.decode('utf8')
            except:
                atr[key] = value
    
    # Try ORBIT_DIRECTION first
    orbit_dir = atr.get('ORBIT_DIRECTION', None)
    if orbit_dir:
        orbit_dir = str(orbit_dir).strip().upper()
        if orbit_dir == 'ASCENDING':
            return 'asc'
        elif orbit_dir == 'DESCENDING':
            return 'desc'
    
    # Fall back to flight_direction
    flight_dir = atr.get('flight_direction', None)
    if flight_dir:
        flight_dir = str(flight_dir).strip().upper()
        if flight_dir in ['A', 'ASCENDING']:
            return 'asc'
        elif flight_dir in ['D', 'DESCENDING']:
            return 'desc'
    
    # Not found
    return None


def get_he5_files(dir, dataset=None):
    '''get dataset*.he5 files in directory'''
    all_files = glob.glob(dir + '/*.he5')

    file_geo = [file for file in all_files if 'DS'  not in file and 'PS' not in file]
    file_PS = [file for file in all_files if 'PS'  in file]
    file_DS = [file for file in all_files if 'DS'  in file and 'filt' not in file]
    file_filtDS = [file for file in all_files if 'DS'  in file and 'filt' in file]
        
    files = []
    suffixes = []
    if dataset == "geo":
        files.append(file_geo)
        suffixes.append("")
    if dataset == "PS":
        files.append(file_PS)
        suffixes.append("_PS")
    if dataset == "DS":
        files.append(file_DS)
        suffixes.append("_DS")
    if dataset == "filt*DS" or dataset == "filtDS"  :
        files.append(file_filtDS)
        suffixes.append("_filtDS")
    if dataset == "DSfilt*DS" or dataset == "DSfiltDS":
        files.append(file_DS)
        files.append(file_filtDS)
        suffixes.append("_DS")
        suffixes.append("_filtDS")
    if dataset == "PSDS" or dataset == "DSPS":
        files.append(file_PS)
        files.append(file_DS)
        suffixes.append("_PS")
        suffixes.append("_DS")
    if dataset == "all":
        files.append(file_geo)
        files.append(file_PS)
        files.append(file_DS)
        suffixes.append("")
        suffixes.append("_PS")
        suffixes.append("_DS")

    if not any(files):
       raise ValueError(f"USER ERROR: no files {dataset} found.")

    return files[0], suffixes[0]
