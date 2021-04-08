import subprocess
import time
import ctypes
import sys
import codecs
import base64

from pathlib import Path

from eth2validatorwizard.constants import *

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

RESUME_CHOCOLATEY = 'resume_chocolatey'

def installation_steps(*args, **kwargs):

    install_chocolatey()

    if not install_nssm():
        # We could not install nssm
        print('Press enter to quit')
        input()
        quit()
    
    print('Press enter to quit')
    input()

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

    return True

def install_nssm():
    # Install nssm for service management

    choco_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'choco')

    # Check to see if choco is installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'])

        if process_result.returncode == 0:
            choco_installed = True
    except FileNotFoundError:
        try:
            process_result = subprocess.run([choco_path, '--version'])

            if process_result.returncode == 0:
                choco_installed = True
        except FileNotFoundError:
            choco_installed = False

    if not choco_installed:
        print('We could not find choco. You might need to close this '
            'window and restart the wizard to continue.')
        return False

    nssm_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'nssm')

    # Check to see if nssm is already installed
    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm', '--version'])

        if process_result.returncode == 0:
            nssm_installed = True
        
    except FileNotFoundError:
        try:
            process_result = subprocess.run([nssm_path, '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
        except FileNotFoundError:
            nssm_installed = False
    
    if nssm_installed:
        print('NSSM is already installed, no need to install it')
        return True
    
    try:
        subprocess.run([
            'choco', 'install', '-y', 'nssm'])
    except FileNotFoundError:
        subprocess.run([
            choco_path, 'install', '-y', 'nssm'])
    
    return True
    
