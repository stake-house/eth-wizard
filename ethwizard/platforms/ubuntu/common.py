import sys
import json
import subprocess
import re
import os
import stat

import logging
import logging.handlers

from pathlib import Path

from secrets import token_hex

from typing import Optional

from ethwizard import __version__

from ethwizard.constants import (
    LINUX_SAVE_DIRECTORY,
    STATE_FILE,
    LINUX_JWT_TOKEN_DIRECTORY,
    LINUX_JWT_TOKEN_FILE_PATH
)

log = logging.getLogger(__name__)

def save_state(step_id: str, context: dict) -> bool:
    # Save wizard state

    data_to_save = {
        'step': step_id,
        'context': context
    }

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        save_directory.mkdir(parents=True, exist_ok=True)
    save_file = save_directory.joinpath(STATE_FILE)

    with open(str(save_file), 'w', encoding='utf8') as output_file:
        json.dump(data_to_save, output_file)

    return True

def load_state() -> Optional[dict]:
    # Load wizard state

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        return None
    save_file = save_directory.joinpath(STATE_FILE)
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
    log.info(f'Quitting eth-wizard')
    quit()

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

    # SysLog handler to log into syslog
    slh = logging.handlers.SysLogHandler(address='/dev/log')

    formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    slh.setFormatter(formatter)

    log.addHandler(slh)

    log.info(f'Starting eth-wizard version {__version__}')

def get_systemd_service_details(service):
    # Return some systemd service details
    
    properties = ('Description', 'LoadState', 'ActiveState', 'ExecMainStartTimestamp',
        'FragmentPath', 'UnitFilePreset', 'SubState', 'ExecStart')

    process_result = subprocess.run([
        'systemctl', 'show', service,
        '--property=' + ','.join(properties)
        ], capture_output=True, text=True)
    process_output = process_result.stdout

    service_details = {}

    for sproperty in properties:
        result = re.search(re.escape(sproperty) + r'=(.*?)\n', process_output)
        if result:
            service_details[sproperty] = result.group(1).strip()
    
    for sproperty in properties:
        if sproperty not in service_details:
            service_details[sproperty] = 'unknown'

    return service_details

def is_package_installed(package):
    process_result = subprocess.run(['apt', '-qq', 'list', '--installed', package],
        capture_output=True, text=True)

    if process_result.returncode != 0:
        log.error(f'Unexpected return code from apt when trying to list for installed package '
            f'{package}. Return code: {process_result.returncode}')
        raise Exception(f'Unexpected return code from apt when trying to list for installed '
            f'package {package}. Return code: {process_result.returncode}')
    
    process_output = process_result.stdout
    result = re.search(re.escape(package) + r'/', process_output)
    package_is_installed = result is not None

    return package_is_installed

def is_adx_supported():
    # Detect if ADX instructions set is support on this CPU

    with open('/proc/cpuinfo', 'r') as cpuinfo_file:
        line = cpuinfo_file.readline()
        while line:
            result = re.search(r'flags\s+\:\s*(.*)', line)
            if result:
                cpuflags = set(result.group(1).strip().lower().split(' '))

                adx_support = ('adx' in cpuflags)

                if adx_support:
                    log.info('ADX instructions set is supported on this CPU.')
                else:
                    log.warn('ADX instructions set is NOT supported on this CPU.')

                return adx_support
            line = cpuinfo_file.readline()
        
        log.warning('No CPU flags found in /proc/cpuinfo. '
            'Could not find if ADX instructions are supported.')

    return False

def setup_jwt_token_file():
    # Create or ensure that the JWT token file exist

    create_jwt_token = False
    jwt_token_path = Path(LINUX_JWT_TOKEN_FILE_PATH)

    if not jwt_token_path.is_file():
        create_jwt_token = True
    
    if create_jwt_token:
        jwt_token_directory = Path(LINUX_JWT_TOKEN_DIRECTORY)
        jwt_token_directory.mkdir(parents=True, exist_ok=True)

        with open(LINUX_JWT_TOKEN_FILE_PATH, 'w') as jwt_token_file:
            jwt_token_file.write(token_hex(32))

        # Make the file readable for everyone
        st = os.stat(LINUX_JWT_TOKEN_FILE_PATH)
        os.chmod(LINUX_JWT_TOKEN_FILE_PATH,
            st.st_mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    return True

def is_ethereum_ppa_added():
    # Check if the official Ethereum PPA has been added

    sources_content = ''
    with open('/etc/apt/sources.list', 'r') as sources_file:
        sources_content = sources_file.read()

    result = re.search(r'^deb\s+https?\://ppa\.launchpad(content)?\.net/ethereum/ethereum/ubuntu',
        sources_content, re.MULTILINE)
    if result:
        return True
    
    with os.scandir('/etc/apt/sources.list.d/') as it:
        for entry in it:
            if entry.name.startswith('.') or not entry.is_file():
                continue

            sources_content = ''
            with open(entry.path, 'r') as sources_file:
                sources_content = sources_file.read()
            
            result = re.search(r'^deb\s+https?\://ppa\.launchpad(content)?\.net/ethereum/ethereum/ubuntu',
                sources_content, re.MULTILINE)
            if result:
                return True
                
    return False

def is_nethermind_ppa_added():
    # Check if the Nethermind PPA has been added

    sources_content = ''
    with open('/etc/apt/sources.list', 'r') as sources_file:
        sources_content = sources_file.read()

    result = re.search(r'^deb\s+https?\://ppa\.launchpad(content)?\.net/nethermindeth/nethermind/ubuntu',
        sources_content, re.MULTILINE)
    if result:
        return True
    
    with os.scandir('/etc/apt/sources.list.d/') as it:
        for entry in it:
            if entry.name.startswith('.') or not entry.is_file():
                continue

            sources_content = ''
            with open(entry.path, 'r') as sources_file:
                sources_content = sources_file.read()
            
            result = re.search(r'^deb\s+https?\://ppa\.launchpad(content)?\.net/nethermindeth/nethermind/ubuntu',
                sources_content, re.MULTILINE)
            if result:
                return True
                
    return False