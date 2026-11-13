#!/usr/bin/env python3
#####################################
#Author: Sara Mirzaee
# based on stackSentinel.py
#####################################
import os
import sys
import subprocess
from argparse import Namespace
import shutil
import glob
import shlex
from minsar.utils.process_utilities import make_run_list
from minsar.objects.auto_defaults import PathFind
import contextlib
from minsar.objects import message_rsmas
import logging
import xml.etree.ElementTree as ET
mpl_logger = logging.getLogger('matplotlib')
mpl_logger.setLevel(logging.WARNING)

pathObj = PathFind()
###########################################


class CreateRun:

    def __init__(self, inps):

        self.work_dir = inps.work_dir
        self.prefix = inps.prefix
        self.is_alos2_stack = (
            inps.prefix == 'stripmap'
            and str(inps.template.get('stripmapStack.sensor', '')).upper().replace('-', '') == 'ALOS2'
        )
        if inps.prefix == 'tops':
            self.workflow = inps.template['topsStack.workflow']
        self.geo_reference_dir = os.path.join(self.work_dir, pathObj.georeferencedir)
        self.miaplpy_dir = os.path.join(self.work_dir, pathObj.miaplpydir)

        self.inps = inps
        self.inps.custom_template_file = inps.custom_template_file

        self.command_options = []
        for item in inps.Stack_template:
            if item in ['useGPU', 'rmFilter', 'nofocus', 'zero', 'applyWaterMask']:
                if inps.Stack_template[item] in ['True', True]:
                    self.command_options.append('--' + item)
            elif item in ['bbox', 'swath_num']:
                self.command_options.append('--' + item)
                self.command_options.append('"{}"'.format(inps.Stack_template[item]))
            elif inps.Stack_template[item]:
                self.command_options.append('--' + item)
                self.command_options.append(inps.Stack_template[item])

        clean_list = pathObj.isce_clean_list()
        for item in clean_list[0]:
            if os.path.isdir(os.path.join(inps.work_dir, item)):
                shutil.rmtree(os.path.join(inps.work_dir, item))

        return

    def run_stack_workflow(self):        # This part is for isce stack run_files
        if self.is_alos2_stack:
            self._run_alos2_stack()
            return
        elif self.prefix == 'tops':
            message_rsmas.log(self.work_dir, 'stackSentinel.py' + ' ' + ' '.join(self.command_options))
            cmd = 'export PATH=$ISCE_STACK/topsStack:$PATH; stackSentinel.py' + ' ' + ' '.join(self.command_options)

        else:
            message_rsmas.log(self.work_dir, 'stackStripMap.py' + ' ' + ' '.join(self.command_options))
            cmd = 'export PATH=$ISCE_STACK/stripmapStack:$PATH; stackStripMap.py' + ' ' + ' '.join(self.command_options)
        
        system_path = os.getenv('PATH')

        print (cmd)
        status = subprocess.Popen(cmd, shell=True).wait()
        if status is not 0:
             raise Exception('ERROR in create_runfiles.py')

        os.environ['PATH'] = system_path

        woke_PBS_job_files=glob.glob(self.work_dir + '/run_files/*.job')
        for f in woke_PBS_job_files:
            os.remove(f)
        
        return

    def _run_alos2_stack(self):
        """Create alosStack XML and script-style MinSAR run files."""
        slc_dir = os.path.abspath(self.inps.template['stripmapStack.slcDir'])
        date_dirs = sorted(
            os.path.basename(path)
            for path in glob.glob(os.path.join(slc_dir, '[0-9]' * 6))
            if os.path.isdir(path)
        )
        if not date_dirs:
            raise RuntimeError(f'No alosStack YYMMDD acquisition directories found in {slc_dir}')

        dem_file = os.path.abspath(self.inps.template['stripmapStack.demDir'])
        water_body = self.inps.template.get('alos2Stack.waterBody', 'auto')
        if water_body in (None, 'None', 'auto'):
            matches = sorted(glob.glob(os.path.join(os.path.dirname(dem_file), '*.wbd')))
            if not matches:
                raise RuntimeError('No water-body file found. Set alos2Stack.waterBody or run wbd.py for the DEM bounds.')
            water_body = matches[0]
        water_body = os.path.abspath(water_body)

        reference_date = self.inps.template.get('stripmapStack.referenceDate')
        if reference_date in (None, 'None', 'auto'):
            reference_date = date_dirs[0]
        if len(reference_date) == 8:
            reference_date = reference_date[2:]
        if reference_date not in date_dirs:
            raise RuntimeError(f'ALOS-2 reference date {reference_date} is not present in {slc_dir}')

        root = ET.Element('stack')
        component = ET.SubElement(root, 'component', {'name': 'stackinsar'})
        properties = {
            'data directory': slc_dir,
            'dem for coregistration': dem_file,
            'dem for geocoding': dem_file,
            'water body': water_body,
            'reference date of the stack': reference_date,
            'polarization': self.inps.template.get('alos2Stack.polarization', 'HH'),
            'number of subsequent dates': self.inps.template.get('alos2Stack.numberOfSubsequentDates', '4'),
            'geocode bounding box': f"[{self.inps.template['stripmapStack.boundingBox'].replace(' ', ', ')}]",
            'do ionospheric phase estimation': self.inps.template.get('alos2Stack.doIonosphere', 'False'),
            'apply ionospheric phase correction': self.inps.template.get('alos2Stack.applyIonosphere', 'False'),
        }
        for name, value in properties.items():
            node = ET.SubElement(component, 'property', {'name': name})
            node.text = str(value)

        xml_path = os.path.join(self.work_dir, 'alosStack.xml')
        ET.indent(root)
        ET.ElementTree(root).write(xml_path, encoding='utf-8', xml_declaration=True)

        command = [os.path.join(os.getenv('ISCE_STACK'), 'alosStack', 'create_cmds.py'), '-stack_par', xml_path]
        message_rsmas.log(self.work_dir, ' '.join(command))
        print(' '.join(command))
        subprocess.run(command, cwd=self.work_dir, check=True)

        command_dir = os.path.join(self.work_dir, 'alos2_cmds')
        os.makedirs(command_dir, exist_ok=True)
        labels = ('prepare', 'interferograms', 'ionosphere', 'finalize')
        run_dir = os.path.join(self.work_dir, 'run_files')
        for index, label in enumerate(labels, start=1):
            source = os.path.join(self.work_dir, f'cmd_{index}.sh')
            destination = os.path.join(command_dir, f'cmd_{index}.sh')
            shutil.move(source, destination)
            run_file = os.path.join(run_dir, f'run_{index:02d}_alos2_{label}')
            with open(run_file, 'w') as file:
                file.write(f'bash {shlex.quote(destination)}\n')

