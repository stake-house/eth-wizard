import os
import sys
import json
import subprocess
import re

import logging

from pathlib import Path

from typing import Optional

from ethwizard import __version__

from ethwizard.constants import (
    STATE_FILE,
    CHOCOLATEY_DEFAULT_BIN_PATH
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