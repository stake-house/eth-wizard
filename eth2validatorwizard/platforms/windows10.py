import subprocess
import time
import ctypes
import sys
import codecs
import base64
import os

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

    env = os.environ.copy()
    env['PATH'] = env['PATH'] + ';' + CHOCOLATEY_DEFAULT_BIN_PATH

    # Check to see if choco is installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'], env=env)

        if process_result.returncode == 0:
            choco_installed = True
    except FileNotFoundError:
        choco_installed = False

    if not choco_installed:
        print('We could not find choco. You might need to close this '
            'windows and restart the wizard to continue.')
        return False

    # Check to see if nssm is already installed
    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm', '--version'], env=env)

        if process_result.returncode == 0:
            nssm_installed = True
            
            print('NSSM is already installed, no need to install it')

    except FileNotFoundError:
        nssm_installed = False
    
    if nssm_installed:
        return True
    
    subprocess.run([
        'choco', 'install', '-y', 'nssm'], env=env)
    
    return True
    
