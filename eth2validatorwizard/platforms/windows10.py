import subprocess
import time
import ctypes
import sys
import codecs
import base64

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

RESUME_CHOCOLATEY = 'resume_chocolatey'

def installation_steps(*args, **kwargs):

    if 'resume_chocolatey' not in kwargs:
        install_chocolatey()

    install_nssm()

def install_chocolatey():
    # Install chocolatey to obtain other tools

    # Check to see if choco is already installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'])

        if process_result.returncode == 0:
            choco_installed = True
            
            print('Chocolatey is already installed, we will update it to the latest version')
            subprocess.run([
                'choco', 'upgrade', 'chocolatey'])

    except FileNotFoundError:
        choco_installed = False

    if choco_installed:
        return True

    print('Chocolatey is not installed, we will install it')
    subprocess.run([
        'powershell', '-Command',
        "& {Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))}"
        ])

    reload_delay = 5

    print(f'We need to reload the session to continue here. Reloading in {reload_delay} seconds.')
    time.sleep(reload_delay)

    # Refresh or reload environment for access to choco binary
    pythonpath_env = rf'$env:PYTHONPATH = "{";".join(sys.path)}";'
    target_command = (
        pythonpath_env + sys.executable + ' ' + ' '.join(sys.argv) + ' ' + RESUME_CHOCOLATEY)
    encoded_command = base64.b64encode(codecs.encode(target_command, 'utf_16_le'))
    encoded_command = codecs.decode(encoded_command, 'ascii')
    args = f'-NoExit -NoProfile -EncodedCommand {encoded_command}'
    ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', 'powershell', args, None, 1)
    
    subprocess.run(['exit'])
    quit()

def install_nssm():
    # Install nssm for service management

    # Check to see if nssm is already installed
    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm'])

        if process_result.returncode == 0:
            nssm_installed = True
            
            print('NSSM is already installed, no need to install it')

    except FileNotFoundError:
        nssm_installed = False
    
    if nssm_installed:
        return True
    
    subprocess.run([
        'choco', 'install', 'nssm'])
    
    return True
    
