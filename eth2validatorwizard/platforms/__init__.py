import os
import platform
import subprocess
import re
import ctypes
import sys
import codecs
import base64

from packaging import version

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
            from eth2validatorwizard.platforms.windows10 import log
            log.info('Performing privilege elevation')

            pythonpath_env = rf'$env:PYTHONPATH = "{";".join(sys.path)}";'
            encoding_change = (
                '$OutputEncoding = [console]::InputEncoding = '
                '[console]::OutputEncoding = New-Object System.Text.UTF8Encoding;'
            )
            target_command = (
                encoding_change +
                pythonpath_env +
                sys.executable + ' ' + " ".join(sys.argv)
            )
            encoded_command = base64.b64encode(codecs.encode(target_command, 'utf_16_le'))
            encoded_command = codecs.decode(encoded_command, 'ascii')
            args = f'-NoProfile -EncodedCommand {encoded_command}'
            ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', 'powershell', args, None, 1)
        
        # End the unprivileged process
        sys.exit()
    
    return False

def init_logging(platform):
    if platform == PLATFORM_UBUNTU:
        from eth2validatorwizard.platforms.ubuntu import init_logging
        return init_logging()
    elif platform == PLATFORM_WINDOWS10:
        from eth2validatorwizard.platforms.windows10 import init_logging
        return init_logging()
    
    return False

def quit_install(platform):
    if platform == PLATFORM_UBUNTU:
        from eth2validatorwizard.platforms.ubuntu import quit_install
        return quit_install()
    elif platform == PLATFORM_WINDOWS10:
        from eth2validatorwizard.platforms.windows10 import quit_install
        return quit_install()
    
    return False

def get_install_steps(platform):
    if platform == PLATFORM_UBUNTU:
        from eth2validatorwizard.platforms.ubuntu import installation_steps as ubuntu_steps
        return ubuntu_steps
    elif platform == PLATFORM_WINDOWS10:
        from eth2validatorwizard.platforms.windows10 import installation_steps as windows10_steps
        return windows10_steps
    
    return False

def resume_step(platform):
    if platform == PLATFORM_WINDOWS10:
        from eth2validatorwizard.platforms.windows10 import RESUME_CHOCOLATEY
        if RESUME_CHOCOLATEY in sys.argv:
            from eth2validatorwizard.platforms.windows10 import installation_steps as windows10_steps
            windows10_steps(resume_chocolatey=True)
            return True
    
    return False
        