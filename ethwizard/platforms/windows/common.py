import os
import sys
import json
import subprocess
import re
import httpx

import logging

from pathlib import Path

from urllib.parse import urljoin, urlparse

from collections.abc import Collection

from secrets import token_hex

from typing import Optional

from ethwizard import __version__

from ethwizard.constants import (
    STATE_FILE,
    CHOCOLATEY_DEFAULT_BIN_PATH,
    GNUPG_DOWNLOAD_URL
)

log = logging.getLogger(__name__)

def save_state(step_id: str, context: dict) -> bool:
    # Save wizard state

    data_to_save = {
        'step': step_id,
        'context': context
    }

    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if not app_data.is_dir():
        return False
    
    app_dir = app_data.joinpath('eth-wizard')
    app_dir.mkdir(parents=True, exist_ok=True)
    save_file = app_dir.joinpath(STATE_FILE)

    with open(str(save_file), 'w', encoding='utf8') as output_file:
        json.dump(data_to_save, output_file)

    return True

def load_state() -> Optional[dict]:
    # Load wizard state

    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if not app_data.is_dir():
        return None
    
    app_dir = app_data.joinpath('eth-wizard')
    if not app_dir.is_dir():
        return None
    
    save_file = app_dir.joinpath(STATE_FILE)
    if not save_file.is_file():
        return None
    
    loaded_data = None

    try:
        with open(str(save_file), 'r', encoding='utf8') as input_file:
            loaded_data = json.load(input_file)
    except ValueError:
        return None
    
    return loaded_data

def quit_app():
    print('Press enter to quit')
    input()
    
    log.info(f'Quitting eth-wizard')
    sys.exit()

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    log.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

def init_logging():
    # Initialize logging
    log.setLevel(logging.INFO)

    # Handle uncaught exception and log them
    sys.excepthook = handle_exception

    # Console handler to log into the console
    ch = logging.StreamHandler()
    log.addHandler(ch)

    # File handler to log into a file
    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if app_data.is_dir():
        app_dir = app_data.joinpath('eth-wizard')
        app_dir.mkdir(parents=True, exist_ok=True)
        log_file = app_dir.joinpath('app.log')
        fh = logging.FileHandler(log_file, encoding='utf8')

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)

        log.addHandler(fh)

    log.info(f'Starting eth-wizard version {__version__}')

def get_service_details(nssm_binary, service):
    # Return some service details

    process_result = subprocess.run([
        str(nssm_binary), 'dump', service
        ], capture_output=True, text=True, encoding='utf8')
    
    if process_result.returncode != 0:
        return None

    service_details = {
        'install': None,
        'status': None,
        'parameters': {}
    }

    process_output = process_result.stdout
    result = re.search(r'nssm\.exe install \S+( (?P<install>.+))?', process_output)
    if result:
        service_details['install'] = result.group('install')

    for result in re.finditer(r'nssm.exe set \S+( (?P<param>\S+))?( (?P<quote>("|\^"))?(?P<value>.+?)(?P=quote)?)?(\n|$)', process_output):
        param = result.group('param')
        value = result.group('value')
        if result.group('quote') == '^"':
            value = re.sub(r'\^(?P<char>.)', r'\g<char>', value)
            value = re.sub(r'\\"', r'"', value)
        if param is not None:
            service_details['parameters'][param] = value
    
    process_result = subprocess.run([
        str(nssm_binary), 'status', service
        ], capture_output=True, text=True, encoding='utf8')
    
    if process_result.returncode == 0:
        process_output = process_result.stdout
        service_details['status'] = process_output.strip()

    return service_details

def get_nssm_binary():
    # Check for nssm install and path
    nssm_path = Path(CHOCOLATEY_DEFAULT_BIN_PATH, 'nssm')
    nssm_binary = 'nssm'

    nssm_installed = False

    try:
        process_result = subprocess.run(['nssm', '--version'])

        if process_result.returncode == 0:
            nssm_installed = True
        
    except FileNotFoundError:
        try:
            process_result = subprocess.run([str(nssm_path), '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
                nssm_binary = nssm_path
        except FileNotFoundError:
            nssm_installed = False
    
    if not nssm_installed:
        log.error('NSSM is not installed, we cannot continue.')
        return False
    
    return nssm_binary

def is_stable_windows_amd64_archive(name):
    return (
        name.find('windows') != -1 and
        name.endswith('.zip') and
        name.find('amd64') != -1 and
        name.find('unstable') == -1 and
        name.find('alltools') == -1
    )

def install_gpg(base_directory):
    # Install the GPG binary

    # Check if gnupg is already installed
    gpg_installed = False

    gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

    if gpg_binary_path.is_file():
        process_result = subprocess.run([
            str(gpg_binary_path), '--version'
        ])

        if process_result.returncode == 0:
            gpg_installed = True

    if gpg_installed:
        log.info('GNUPG is already installed, no need to install it')
        return True

    # Get the gnupg install URL
    gpg_installer_url = None
    try:
        response = httpx.get(GNUPG_DOWNLOAD_URL, follow_redirects=True)
        
        if response.status_code != 200:
            log.error(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\n'
                f'Unexpected status code {response.status_code}')
            return False
        
        response_text = response.text
        match = re.search(r'href="(?P<url>[^"]+gnupg-w32-[^"]+.exe)"', response_text)
        if not match:
            log.error(f'Cannot find GNUPG installer on GNUPG download URL {GNUPG_DOWNLOAD_URL}.')
            return False
        
        gpg_installer_url = urljoin(GNUPG_DOWNLOAD_URL, match.group('url'))
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\n'
            f'Exception {exception}')
        return False

    if gpg_installer_url is None:
        return False
    
    download_path = base_directory.joinpath('downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    # Download the gnupg installer
    file_name = urlparse(gpg_installer_url).path.split('/')[-1]
    download_installer_path = download_path.joinpath(file_name)

    if download_installer_path.is_file():
        download_installer_path.unlink()

    try:
        with open(download_installer_path, 'wb') as binary_file:
            log.info('Downloading GNUPG installer...')
            with httpx.stream('GET', gpg_installer_url, follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'Cannot download GNUPG installer {gpg_installer_url}.\n'
                        f'Unexpected status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading GNUPG installer. Exception {exception}')
        return False

    # Run installer silently
    log.info('Installing GNUPG...')

    process_result = subprocess.run([
        str(download_installer_path), '/S', '/D=' + str(base_directory)
    ])

    if process_result.returncode != 0:
        log.error(f'Failed to install GNUPG. Return code {process_result.returncode}')
        return False

    # Remove download leftovers
    download_installer_path.unlink()

    if not gpg_binary_path.is_file():
        log.error(f'Could not find GPG binary after installation. '
            f'Expected to be in {gpg_binary_path}')
        return False
    
    process_result = subprocess.run([
        str(gpg_binary_path), '--version'
    ])

    if process_result.returncode != 0:
        log.error(f'Unexpected return from gpg binary. Return code {process_result.returncode}')
        return False

    return True

def set_service_param(nssm_binary, service_name, param, value):
    # Configure an NSSM service paramater with a value
    if type(value) is str:
        process_result = subprocess.run([
            str(nssm_binary), 'set', service_name, param, value
            ])
    elif isinstance(value, Collection):
        process_result = subprocess.run([
            str(nssm_binary), 'set', service_name, param
            ] + list(value))
    else:
        log.error(f'Unexpected parameter value {value} for parameter {param}.')
        return False
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from NSSM when modifying at parameter. '
            f'Return code {process_result.returncode}')
        return False
    
    return True

def setup_jwt_token_file(base_directory):
    # Create or ensure that the JWT token file exist

    create_jwt_token = False
    jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
    jwt_token_path = jwt_token_dir.joinpath('jwttoken')

    if not jwt_token_path.is_file():
        create_jwt_token = True
    
    if create_jwt_token:
        jwt_token_dir.mkdir(parents=True, exist_ok=True)

        with open(jwt_token_path, 'w') as jwt_token_file:
            jwt_token_file.write(token_hex(32))

    return True