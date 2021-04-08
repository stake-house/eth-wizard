import subprocess

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

def installation_steps():

    install_chocolatey()

    # TODO: Install nssm

def install_chocolatey():
    # Install chocolatey to obtain other tools

    # Check if choco is already installed
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

    # TODO: Need to refresh or reload environment for access to choco binary
