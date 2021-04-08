import os
import platform
import subprocess
import re
import ctypes
import sys

from packaging import version

from eth2validatorwizard.platform.ubuntu import installation_steps as ubuntu_steps
from eth2validatorwizard.platform.windows10 import installation_steps as windows10_steps

PLATFORM_UBUNTU = 'Ubuntu'
PLATFORM_WINDOWS10 = 'Windows10'

def supported_platform():
    # Test if the current platform is supported and return platform code

    uname = platform.uname()
    if (
        uname.system == 'Linux' and
        uname.machine.lower() == 'x86_64'):
        # We are on Linux amd64

        # Obtain distribution information with lsb_release
        process_result = subprocess.run([
            'lsb_release', '-a'
            ], capture_output=True, text=True)
        
        if process_result.returncode != 0:
            print(f'Unable to run lsb_release. Return code {process_result.returncode}')
            print(f'{process_result.stdout}\n{process_result.stderr}')
            return False
        
        process_output = process_result.stdout

        lsb_distributor_id = None
        lsb_release = None

        result = re.search(r'Distributor ID:\s*(.+)', process_output)
        if result:
            lsb_distributor_id = result.group(1).strip()
        result = re.search(r'Release:\s*(.+)', process_output)
        if result:
            lsb_release = result.group(1).strip()
        
        if lsb_distributor_id is None or lsb_release is None:
            print('Unable to parse Distributor ID or Release from lsb_release output.')
            print(f'{process_output}')
            return False

        if lsb_distributor_id == 'Ubuntu':
            base_version = version.parse('20.04')

            if version.parse(lsb_release) >= base_version:
                return PLATFORM_UBUNTU
    elif (
        uname.system == 'Windows' and
        uname.release == '10' and
        uname.machine.lower() == 'amd64'):

        return PLATFORM_WINDOWS10

    return False

def has_su_perm(platform):
    if platform == PLATFORM_UBUNTU:
        # Check to see if the script has super user (root or sudo) permissions
        return os.geteuid() == 0
    elif platform == PLATFORM_WINDOWS10:
        perform_elevation = False
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                return True
            else:
                perform_elevation = True
        except:
            perform_elevation = True
        
        if perform_elevation:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        
        # End the unprivileged process
        quit()
    
    return False

def get_install_steps(platform):
    if platform == PLATFORM_UBUNTU:
        return ubuntu_steps
    elif platform == PLATFORM_WINDOWS10:
        return windows10_steps
    
    return False