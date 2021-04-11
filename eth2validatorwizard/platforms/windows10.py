import subprocess
import time
import ctypes
import sys
import codecs
import base64
import httpx
import re
import os
import shutil
import json

from pathlib import Path

from urllib.parse import urljoin, urlparse

from defusedxml import ElementTree

from dateutil.parser import parse as dateparse

from zipfile import ZipFile

from eth2validatorwizard.constants import *

from eth2validatorwizard.platforms.common import (
    select_network,
    select_eth1_fallbacks,
    input_dialog_default,
)

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

RESUME_CHOCOLATEY = 'resume_chocolatey'

def installation_steps(*args, **kwargs):

    selected_ports = {
        'eth1': DEFAULT_GETH_PORT,
        'eth2_bn': DEFAULT_LIGHTHOUSE_BN_PORT
    }

    selected_directory = select_directory()
    if not selected_directory:
        # User asked to quit
        quit_install()

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit_install()

    if not install_chocolatey():
        # We could not install chocolatey
        quit_install()

    if not install_nssm():
        # We could not install nssm
        quit_install()

    if not install_geth(selected_directory, selected_network, selected_ports):
        # User asked to quit or error
        quit_install()
    
    # Teku does not support fallback yet
    '''selected_eth1_fallbacks = select_eth1_fallbacks(selected_network)
    if type(selected_eth1_fallbacks) is not list and not selected_eth1_fallbacks:
        # User asked to quit
        quit_install()'''

    if not install_teku(selected_directory, selected_network, selected_ports):
        # User asked to quit or error
        quit_install()

    print('Press enter to quit')
    input()

def quit_install():
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
    
    try:
        subprocess.run([
            'choco', 'install', '-y', 'nssm'])
    except FileNotFoundError:
        subprocess.run([
            choco_path, 'install', '-y', 'nssm'])
    
    return True
    
def select_directory():
    directory_valid = False
    selected_directory = None
    input_canceled = False
    default_directory = r'c:\ethereum'

    while not directory_valid:
        not_valid_msg = ''
        if selected_directory is not None:
            not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>an invalid directory</b>. Please make sure to enter a valid
directory.</style>'''
            )

        default_input_text = default_directory

        if selected_directory is not None:
            default_input_text = selected_directory

        selected_directory = input_dialog_default(
            title='Enter a directory',
            text=(HTML(
f'''
Please enter a directory where ethereum clients and their data will be
stored:

Ideally you want to select an empty directory that does not contain any
space or international character in its path. You also want to make sure
you select a directory on your fast disk that has enough space for ethereum
data.

If the directory does not exist, we will attempt to create it for you.

* Press the tab key to switch between the controls below{not_valid_msg}
'''         )),
            default_input_text=default_input_text).run()

        if not selected_directory:
            input_canceled = True
            break
        
        directory_valid = directory_validator(selected_directory)

    if input_canceled:
        # User clicked the cancel button
        return False

    return Path(selected_directory)

def directory_validator(directory):
    try:
        directory_path = Path(directory)
        directory_path.mkdir(parents=True, exist_ok=True)
        return directory_path.is_dir()
    except OSError:
        return False

    return False

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
            process_result = subprocess.run([nssm_path, '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
                nssm_binary = nssm_path
        except FileNotFoundError:
            nssm_installed = False
    
    if not nssm_installed:
        print('NSSM is not installed, we cannot continue.')
        return False
    
    return nssm_binary

def install_geth(base_directory, network, ports):
    # Install geth for the selected network

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    geth_service_exists = False
    geth_service_name = 'geth'

    service_details = get_service_details(nssm_binary, geth_service_name)

    if service_details is not None:
        geth_service_exists = True

    if geth_service_exists:
        result = button_dialog(
            title='Geth service found',
            text=(
f'''
The geth service seems to have already been created. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing geth and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        if result == 1:
            return True
        
        # User wants to proceed, make sure the geth service is stopped first
        subprocess.run([
            nssm_binary, 'stop', geth_service_name])

    result = button_dialog(
        title='Geth installation',
        text=(
'''
This next step will install Geth, an Eth1 client.

It will download the official binary, verify its PGP signature and extract
it for easy use.

Once the installation is completed, it will create a system service that
will automatically start Geth on reboot or if it crashes. Geth will be
started and you will slowly start syncing with the Ethereum 1.0 network.
This syncing process can take a few hours or days even with good hardware
and good internet. We will perform a few tests to make sure Geth is running
properly.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Check if geth is already installed
    geth_path = base_directory.joinpath('bin', 'geth.exe')

    geth_found = False
    geth_version = 'unknown'

    if geth_path.is_file():
        try:
            process_result = subprocess.run([
                geth_path, 'version'
                ], capture_output=True, text=True, encoding='utf8')
            geth_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (.*?)\n', process_output)
            if result:
                geth_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
    install_geth_binary = True

    if geth_found:
        result = button_dialog(
            title='Geth binary found',
            text=(
f'''
The geth binary seems to have already been installed. Here are some
details found:

Version: {geth_version}
Location: {geth_path}

Do you want to skip installing the geth binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_geth_binary = (result == 2)

    if install_geth_binary:
        # Install Geth from official website
        
        # Get list of geth releases/builds from their store
        next_marker = None
        page_end_found = False

        windows_builds = []

        try:
            print('Getting geth builds...')
            while not page_end_found:
                params = GETH_STORE_BUILDS_PARAMS.copy()
                if next_marker is not None:
                    params['marker'] = next_marker

                response = httpx.get(GETH_STORE_BUILDS_URL, params=params)

                if response.status_code != 200:
                    print(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\n'
                    f'Unexpected status code {response.status_code}')
                    return False
                
                builds_tree_root = ElementTree.fromstring(response.text)
                blobs = builds_tree_root.findall('.//Blobs/Blob')

                for blob in blobs:
                    build_name = blob.find('Name').text.strip()
                    if build_name.endswith('.asc'):
                        continue

                    if not is_stable_windows_amd64_archive(build_name):
                        continue

                    build_properties = blob.find('Properties')
                    last_modified_date = dateparse(build_properties.find('Last-Modified').text)

                    windows_builds.append({
                        'name': build_name,
                        'last_modified_date': last_modified_date
                    })

                next_marker = builds_tree_root.find('.//NextMarker').text
                if next_marker is None:
                    page_end_found = True

        except httpx.RequestError as exception:
            print(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\nException {exception}')
            return False

        if len(windows_builds) <= 0:
            print('No geth builds found on geth store. We cannot continue.')
            return False

        # Download latest geth build and its signature
        windows_builds.sort(key=lambda x: (x['last_modified_date'], x['name']), reverse=True)
        latest_build = windows_builds[0]

        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        geth_archive_path = download_path.joinpath(latest_build['name'])
        if geth_archive_path.is_file():
            geth_archive_path.unlink()

        latest_build_url = urljoin(GETH_BUILDS_BASE_URL, latest_build['name'])

        try:
            with open(geth_archive_path, 'wb') as binary_file:
                print(f'Downloading geth archive {latest_build["name"]}...')
                with httpx.stream('GET', latest_build_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download geth archive {latest_build_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading geth archive. Exception {exception}')
            return False

        geth_archive_sig_path = download_path.joinpath(latest_build['name'] + '.asc')
        if geth_archive_sig_path.is_file():
            geth_archive_sig_path.unlink()

        latest_build_sig_url = urljoin(GETH_BUILDS_BASE_URL, latest_build['name'] + '.asc')

        try:
            with open(geth_archive_sig_path, 'wb') as binary_file:
                print(f'Downloading geth archive signature {latest_build["name"]}.asc...')
                with httpx.stream('GET', latest_build_sig_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download geth archive signature {latest_build_sig_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading geth archive signature. Exception {exception}')
            return False

        if not install_gpg(base_directory):
            return False
        
        # Verify PGP signature
        gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

        print('Downloading geth Windows Builder PGP key...')

        command_line = [gpg_binary_path, '--keyserver', 'pool.sks-keyservers.net', '--recv-keys',
            GETH_WINDOWS_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        retry_count = 5
        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            retry_index = 0
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                print('GPG failed to download the PGP key. We will wait 10 seconds and try again.')
                time.sleep(10)
                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP key download
            print(
f'''
We failed to download the Geth Windows Builder PGP key to verify the geth
archive after {retry_count} retries.
'''
)
            return False
        
        process_result = subprocess.run([
            'gpg', '--verify', geth_archive_sig_path])
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP signature
            print('The geth archive signature is wrong. We\'ll stop here to protect you.')
            return False
        
        # Remove download leftovers
        geth_archive_sig_path.unlink()        

        # Unzip geth archive
        bin_path = base_directory.joinpath('bin')
        bin_path.mkdir(parents=True, exist_ok=True)

        geth_extracted_binary = None

        with ZipFile(geth_archive_path, 'r') as zip_file:
            for name in zip_file.namelist():
                if name.endswith('geth.exe'):
                    geth_extracted_binary = Path(zip_file.extract(name, download_path))
        
        # Remove download leftovers
        geth_archive_path.unlink()

        if geth_extracted_binary is None:
            print('The geth binary was not found in the archive. We cannot continue.')
            return False

        # Move geth back into bin directory
        target_geth_binary_path = bin_path.joinpath('geth.exe')
        if target_geth_binary_path.is_file():
            target_geth_binary_path.unlink()
        
        geth_extracted_binary.rename(target_geth_binary_path)

        geth_extracted_binary.parent.rmdir()
    
    # Check if Geth user or directory already exists
    geth_datadir = base_directory.joinpath('var', 'lib', 'goethereum')
    if geth_datadir.is_dir():
        geth_datadir_size = sizeof_fmt(get_dir_size(geth_datadir))

        result = button_dialog(
            title='Geth data directory found',
            text=(
f'''
An existing geth data directory has been found. Here are some
details found:

Location: {geth_datadir}
Size: {geth_datadir_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(geth_datadir)

    # Setup Geth directory
    geth_datadir.mkdir(parents=True, exist_ok=True)
    
    # Setup Geth service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    geth_stdout_log_path = log_path.joinpath('geth-stdout.log')
    geth_stderr_log_path = log_path.joinpath('geth-stderr.log')

    geth_arguments = GETH_ARGUMENTS[network]
    geth_arguments.append('--datadir')
    geth_arguments.append(str(geth_datadir))

    parameters = {
        'DisplayName': GETH_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(geth_stdout_log_path),
        'AppStderr': str(geth_stderr_log_path)
    }

    if not create_service(nssm_binary, geth_service_name, geth_path, geth_arguments, parameters):
        print('There was an issue creating the geth service. We cannot continue.')
        return False
    
    print('Starting geth service...')
    process_result = subprocess.run([
        nssm_binary, 'start', geth_service_name
    ])

    if process_result.returncode != 0:
        print('There was an issue starting the geth service. We cannot continue.')
        return False

    delay = 5
    print(f'We are giving {delay} seconds for the geth service to start properly.')
    time.sleep(delay)
    
    # Verify proper Geth service installation
    service_details = get_service_details(nssm_binary, geth_service_name)
    if not service_details:
        print('We could not find the geth service we just created. We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Geth service not running properly',
            text=(
f'''
The geth service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the geth service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 30 seconds
    log_read_index = 0
    for i in range(6):
        subprocess.run([
            nssm_binary, 'rotate', geth_service_name
        ])
        log_text = ''
        with open(geth_stderr_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(log_read_index)
            log_text = log_file.read()
        
        log_length = len(log_text)
        log_read_index = log_read_index + log_length

        if log_length > 0:
            print(log_text)
        time.sleep(5)

    # Verify proper Geth syncing
    local_geth_jsonrpc_url = 'http://127.0.0.1:8545'
    request_json = {
        'jsonrpc': '2.0',
        'method': 'eth_syncing',
        'id': 1
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
We received an unexpected response from geth HTTP-RPC server. Here are
some details for this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Geth',
                text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Geth',
                text=(
f'''
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
            )

            return False

        response_json = response.json()

    if (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ):
        # We could not get a proper result from Geth after all those retries
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
After a few retries, we still received an unexpected response from geth
HTTP-RPC server. Here are some details for this last test we tried to
perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    response_result = response_json['result']

    if 'currentBlock' not in response_result:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
The response from the eth_syncing JSON-RPC call on Geth HTTP-RPC server
was unexpected. Here are some details for this call:

result field: {json.dumps(response_result)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
Geth is currently syncing properly.

currentBlock: {int(response_result.get('currentBlock', '0x0'), base=16)}
highestBlock: {int(response_result.get('highestBlock', '0x0'), base=16)}
knownStates: {int(response_result.get('knownStates', '0x0'), base=16)}
pulledStates: {int(response_result.get('pulledStates', '0x0'), base=16)}
startingBlock: {int(response_result.get('startingBlock', '0x0'), base=16)}

Raw result: {response_result}
''')
    time.sleep(5)

    return True

def create_service(nssm_binary, service_name, binary_path, binary_args, parameters=None):
    # Create a Windows service using NSSM and configure it

    # Remove it first to make sure it does not exist
    subprocess.run([
        nssm_binary, 'remove', service_name, 'confirm'
    ])

    # Install the service
    process_result = subprocess.run([
        nssm_binary, 'install', service_name, binary_path
        ] + binary_args)

    if process_result.returncode != 0:
        print(f'Unexpected return code from NSSM when installing a new service. '
            f'Return code {process_result.returncode}')
        return False

    # Set all the other parameters
    if parameters is not None:
        for param, value in parameters.items():
            process_result = subprocess.run([
                nssm_binary, 'set', service_name, param, value
                ])
            
            if process_result.returncode != 0:
                print(f'Unexpected return code from NSSM when modifying at parameter. '
                    f'Return code {process_result.returncode}')
                return False
    
    return True

def get_service_details(nssm_binary, service):
    # Return some service details

    process_result = subprocess.run([
        nssm_binary, 'dump', service
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

    for result in re.finditer(r'nssm.exe set \S+( (?P<param>\S+))?( (?P<quote>")?(?P<value>.+)(?P=quote)?)?', process_output):
        param = result.group('param')
        value = result.group('value')
        if param is not None:
            service_details['parameters'][param] = value
    
    process_result = subprocess.run([
        nssm_binary, 'status', service
        ], capture_output=True, text=True, encoding='utf8')
    
    if process_result.returncode == 0:
        process_output = process_result.stdout
        service_details['status'] = process_output.strip()

    return service_details

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
            gpg_binary_path, '--version'
        ])

        if process_result.returncode == 0:
            gpg_installed = True

    if gpg_installed:
        print('GNUPG is already installed, no need to install it')
        return True

    # Get the gnupg install URL
    gpg_installer_url = None
    try:
        response = httpx.get(GNUPG_DOWNLOAD_URL)
        
        if response.status_code != 200:
            print(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\n'
                f'Unexpected status code {response.status_code}')
            return False
        
        response_text = response.text
        match = re.search(r'href="(?P<url>[^"]+gnupg-w32-[^"]+.exe)"', response_text)
        if not match:
            print(f'Cannot find GNUPG installer on GNUPG download URL {GNUPG_DOWNLOAD_URL}.')
            return False
        
        gpg_installer_url = urljoin(GNUPG_DOWNLOAD_URL, match.group('url'))
    except httpx.RequestError as exception:
        print(f'Cannot connect to GNUPG download URL {GNUPG_DOWNLOAD_URL}.\nException {exception}')
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
            print('Downloading GNUPG installer...')
            with httpx.stream('GET', gpg_installer_url) as http_stream:
                if http_stream.status_code != 200:
                    print(f'Cannot download GNUPG installer {gpg_installer_url}.\n'
                        f'Unexpected status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        print(f'Exception while downloading GNUPG installer. Exception {exception}')
        return False

    # Run installer silently
    print('Installing GNUPG...')

    process_result = subprocess.run([
        download_installer_path, '/S', '/D=' + str(base_directory)
    ])

    if process_result.returncode != 0:
        print(f'Failed to install GNUPG. Return code {process_result.returncode}')
        return False

    # Remove download leftovers
    download_installer_path.unlink()

    if not gpg_binary_path.is_file():
        print(f'Could not find GPG binary after installation. Expected to be in {gpg_binary_path}')
        return False
    
    process_result = subprocess.run([
        gpg_binary_path, '--version'
    ])

    if process_result.returncode != 0:
        print(f'Unexpected return from gpg binary. Return code {process_result.returncode}')
        return False

    return True

def install_jre(base_directory):
    # Install adoptopenjdk jre

    # Check if jre is already installed
    jre_path = base_directory.joinpath('bin', 'jre')
    java_path = jre_path.joinpath('bin', 'java.exe')

    jre_found = False
    jre_version = 'unknown'

    if java_path.is_file():
        try:
            process_result = subprocess.run([
                java_path, '--version'
                ], capture_output=True, text=True, encoding='utf8')
            jre_found = True

            process_output = process_result.stdout
            result = re.search(r'OpenJDK Runtime Environment (.*?)\n', process_output)
            if result:
                jre_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
    install_jre = True

    if jre_found:
        result = button_dialog(
            title='JRE found',
            text=(
f'''
The JRE seems to have already been installed. Here are some details found:

Version: {jre_version}
Location: {jre_path}

Do you want to skip installing the JRE?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_jre = (result == 2)
    
    if install_jre:
        windows_builds = []

        try:
            print('Getting JRE builds...')

            response = httpx.get(ADOPTOPENJDK_11_API_URL, params=ADOPTOPENJDK_11_API_PARAMs)

            if response.status_code != 200:
                print(f'Cannot connect to JRE builds URL {ADOPTOPENJDK_11_API_URL}.\n'
                f'Unexpected status code {response.status_code}')
                return False
            
            response_json = response.json()

            if (
                type(response_json) is not list or
                len(response_json) == 0 or
                type(response_json[0]) is not dict or
                'binaries' not in response_json[0]):
                print(f'Unexpected response from JRE builds URL {ADOPTOPENJDK_11_API_URL}')
                return False
            
            binaries = response_json[0]['binaries']
            for binary in binaries:
                if (
                    'architecture' not in binary or
                    'os' not in binary or
                    'package' not in binary or
                    'image_type' not in binary or
                    'updated_at' not in binary):
                    continue
                image_type = binary['image_type']
                architecture = binary['architecture']
                binary_os = binary['os']

                if not (
                    binary_os == 'windows' and
                    architecture == 'x64' and
                    image_type == 'jre'):
                    continue

                package = binary['package']
                updated_at = dateparse(binary['updated_at'])

                if (
                    'name' not in package or
                    'checksum' not in package or
                    'link' not in package):
                    print(f'Unexpected response from JRE builds URL {ADOPTOPENJDK_11_API_URL} in package')
                    return False
                
                package_name = package['name']
                package_link = package['link']
                package_checksum = package['checksum']

                windows_builds.append({
                    'name': package_name,
                    'updated_at': updated_at,
                    'link': package_link,
                    'checksum': package_checksum
                })

        except httpx.RequestError as exception:
            print(f'Cannot connect to JRE builds URL {ADOPTOPENJDK_11_API_URL}.\nException {exception}')
            return False

        if len(windows_builds) <= 0:
            print('No JRE builds found on adoptopenjdk.net. We cannot continue.')
            return False
        
        # Download latest JRE build and its signature
        windows_builds.sort(key=lambda x: (x['updated_at'], x['name']), reverse=True)
        latest_build = windows_builds[0]

        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        jre_archive_path = download_path.joinpath(latest_build['name'])
        if jre_archive_path.is_file():
            jre_archive_path.unlink()

        try:
            with open(jre_archive_path, 'wb') as binary_file:
                print(f'Downloading JRE archive {latest_build["name"]}...')
                with httpx.stream('GET', latest_build['link']) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download JRE archive {latest_build["link"]}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading JRE archive. Exception {exception}')
            return False
        
        # Unzip JRE archive
        archive_members = None

        print(f'Extracting JRE archive {latest_build["name"]}...')
        with ZipFile(jre_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        jre_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            print('No files found in JRE archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if jre_path.is_dir():
            shutil.rmtree(jre_path)
        jre_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, jre_path)
            
        # Make sure jre was installed properly
        jre_found = False
        try:
            process_result = subprocess.run([
                java_path, '--version'
                ], capture_output=True, text=True, encoding='utf8')
            jre_found = True

            process_output = process_result.stdout
            result = re.search(r'OpenJDK Runtime Environment (.*?)\n', process_output)
            if result:
                jre_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
        if not jre_found:
            print(f'We could not find the java binary from the installed JRE in {java_path}. '
                f'We cannot continue.')
            return False
    
    return True

def install_teku(base_directory, network, ports):
    # Install Teku for the selected network

    if not install_jre(base_directory):
        return False

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    teku_bn_service_exists = False
    teku_bn_service_name = 'tekubeacon'

    service_details = get_service_details(nssm_binary, teku_bn_service_name)

    if service_details is not None:
        teku_bn_service_exists = True
    
    if teku_bn_service_exists:
        result = button_dialog(
            title='Teku beacon node service found',
            text=(
f'''
The teku beacon node service seems to have already been created. Here are
some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing teku and its beacon node service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True
        
        # User wants to proceed, make sure the lighthouse beacon node service is stopped first
        subprocess.run([
            nssm_binary, 'stop', teku_bn_service_name])

    # TODO: Finish this step
    return False

    result = button_dialog(
        title='Lighthouse installation',
        text=(
'''
This next step will install Lighthouse, an Eth2 client that includes a
beacon node and a validator client in the same binary.

It will download the official binary from GitHub, verify its PGP signature
and extract it for easy use.

Once installed locally, it will create a service that will automatically
start the Lighthouse beacon node on reboot or if it crashes. The beacon
node will be started and you will slowly start syncing with the Ethereum
2.0 network. This syncing process can take a few hours or days even with
good hardware and good internet.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if lighthouse is already installed
    geth_path = base_directory.joinpath('bin', 'geth.exe')

    lighthouse_found = False
    lighthouse_version = 'unknown'
    lighthouse_location = 'unknown'

    try:
        process_result = subprocess.run([
            'lighthouse', '--version'
            ], capture_output=True, text=True)
        lighthouse_found = True

        process_output = process_result.stdout
        result = re.search(r'Lighthouse (.*?)\n', process_output)
        if result:
            lighthouse_version = result.group(1).strip()
        
        process_result = subprocess.run([
            'whereis', 'lighthouse'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'lighthouse: (.*?)\n', process_output)
        if result:
            lighthouse_location = result.group(1).strip()

    except FileNotFoundError:
        pass
    
    install_lighthouse_binary = True

    if lighthouse_found:
        result = button_dialog(
            title='Lighthouse binary found',
            text=(
f'''
The lighthouse binary seems to have already been installed. Here are some
details found:

Version: {lighthouse_version}
Location: {lighthouse_location}

Do you want to skip installing the lighthouse binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_lighthouse_binary = (result == 2)
    
    if install_lighthouse_binary:
        # Getting latest Lighthouse release files
        lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(lighthouse_gh_release_url, headers=headers)
        except httpx.RequestError as exception:
            print('Cannot connect to Github')
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print('Github returned error code')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
            return False
        
        binary_asset = None
        signature_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('x86_64-unknown-linux-gnu.tar.gz'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
            elif file_name.endswith('x86_64-unknown-linux-gnu.tar.gz.asc'):
                signature_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }

        if binary_asset is None or signature_asset is None:
            # TODO: Better handling of missing asset in latest release
            print('Could not find binary or signature asset in Github release')
            return False
        
        # Downloading latest Lighthouse release files
        download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])

        try:
            with open(binary_path, 'wb') as binary_file:
                with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print('Exception while downloading Lighthouse binary from Github')
            return False
        
        signature_path = Path(download_path, signature_asset['file_name'])

        try:
            with open(signature_path, 'wb') as signature_file:
                with httpx.stream('GET', signature_asset['file_url']) as http_stream:
                    for data in http_stream.iter_bytes():
                        signature_file.write(data)
        except httpx.RequestError as exception:
            print('Exception while downloading Lighthouse signature from Github')
            return False

        # Install gpg using APT
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'gpg'])

        # Verify PGP signature
        command_line = ['gpg', '--keyserver', 'pool.sks-keyservers.net', '--recv-keys',
            LIGHTHOUSE_PRIME_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        retry_count = 5
        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            retry_index = 0
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                print('GPG failed to download the PGP key. We will wait 10 seconds and try again.')
                time.sleep(10)
                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP key download
            print(
f'''
We failed to download the Sigma Prime\'s PGP key to verify the lighthouse
binary after {retry_count} retries.
'''
)
            return False
        
        process_result = subprocess.run([
            'gpg', '--verify', signature_path])
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP signature
            print('The lighthouse binary signature is wrong. We\'ll stop here to protect you.')
            return False
        
        # Extracting the Lighthouse binary archive
        subprocess.run([
            'tar', 'xvf', binary_path, '--directory', '/usr/local/bin'])
        
        # Remove download leftovers
        binary_path.unlink()
        signature_path.unlink()

    # Check if lighthouse beacon node user or directory already exists
    lighthouse_datadir_bn = Path('/var/lib/lighthouse/beacon')
    if lighthouse_datadir_bn.exists() and lighthouse_datadir_bn.is_dir():
        process_result = subprocess.run([
            'du', '-sh', lighthouse_datadir_bn
            ], capture_output=True, text=True)
        
        process_output = process_result.stdout
        lighthouse_datadir_bn_size = process_output.split('\t')[0]

        result = button_dialog(
            title='Lighthouse beacon node data directory found',
            text=(
f'''
An existing lighthouse beacon node data directory has been found. Here are
some details found:

Location: {lighthouse_datadir_bn}
Size: {lighthouse_datadir_bn_size}

Do you want to remove this directory first and start from nothing?
'''         ),
            buttons=[
                ('Remove', 1),
                ('Keep', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            shutil.rmtree(lighthouse_datadir_bn)

    lighthouse_bn_user_exists = False
    process_result = subprocess.run([
        'id', '-u', 'lighthousebeacon'
    ])
    lighthouse_bn_user_exists = (process_result.returncode == 0)

    # Setup Lighthouse beacon node user and directory
    if not lighthouse_bn_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', 'lighthousebeacon'])
    subprocess.run([
        'mkdir', '-p', '/var/lib/lighthouse/beacon'])
    subprocess.run([
        'chown', '-R', 'lighthousebeacon:lighthousebeacon', '/var/lib/lighthouse/beacon'])
    subprocess.run([
        'chmod', '700', '/var/lib/lighthouse/beacon'])

    # Setup Lighthouse beacon node systemd service
    service_definition = LIGHTHOUSE_BN_SERVICE_DEFINITION[network]

    eth1_endpoints = ['http://127.0.0.1:8545'] + eth1_fallbacks
    service_definition = service_definition.format(eth1endpoints=','.join(eth1_endpoints))

    with open('/etc/systemd/system/' + lighthouse_bn_service_name, 'w') as service_file:
        service_file.write(service_definition)
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', lighthouse_bn_service_name])
    subprocess.run([
        'systemctl', 'enable', lighthouse_bn_service_name])
    
    print(
'''
We are giving the lighthouse beacon node a few seconds to start before testing
it.

You might see some error and warn messages about your eth1 node not being in
sync, being far behind or about the beacon node being unable to connect to any
eth1 node. Those message are normal to see while your eth1 client is syncing.
'''
)
    time.sleep(6)
    try:
        subprocess.run([
            'journalctl', '-fu', lighthouse_bn_service_name
        ], timeout=30)
    except subprocess.TimeoutExpired:
        pass

    # Check if the Lighthouse beacon node service is still running
    service_details = get_systemd_service_details(lighthouse_bn_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Lighthouse beacon node service not running properly',
            text=(
f'''
The lighthouse beacon node service we just created seems to have issues.
Here are some details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the lighthouse beacon node service cannot be started
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    # Verify proper Lighthouse beacon node installation and syncing
    local_lighthouse_bn_http_base = 'http://127.0.0.1:5052'
    
    lighthouse_bn_version_query = '/eth/v1/node/version'
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_version_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(lighthouse_bn_query_url, headers=headers)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Lighthouse beacon node',
            text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Lighthouse beacon node',
            text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    # Verify proper Lighthouse beacon node syncing
    lighthouse_bn_syncing_query = '/eth/v1/node/syncing'
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_syncing_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(lighthouse_bn_query_url, headers=headers)
    except httpx.RequestError as exception:
        button_dialog(
            title='Cannot connect to Lighthouse beacon node',
            text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    if response.status_code != 200:
        button_dialog(
            title='Cannot connect to Lighthouse beacon node',
            text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Lighthouse beacon node',
            text=(
f'''
We received an unexpected response from the lighthouse beacon node HTTP
server. Here are some details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()
        
        if not result:

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.get(lighthouse_bn_query_url, headers=headers)
        except httpx.RequestError as exception:
            button_dialog(
                title='Cannot connect to Lighthouse beacon node',
                text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
    '''         ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False

        if response.status_code != 200:
            button_dialog(
                title='Cannot connect to Lighthouse beacon node',
                text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
    '''         ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False
        
        response_json = response.json()
    
    if (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ):
        # We could not get a proper result from the Lighthouse beacon node after all those retries
        result = button_dialog(
            title='Unexpected response from Lighthouse beacon node',
            text=(
f'''
After a few retries, we still received an unexpected response from the
lighthouse beacon node HTTP server. Here are some details for this last
test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
The lighthouse beacon node is currently syncing properly.

Head slot: {response_json['data'].get('head_slot', 'unknown')}
Sync distance: {response_json['data'].get('sync_distance', 'unknown')}

Raw data: {response_json['data']}
''' )
    time.sleep(5)

    return True

def get_dir_size(directory):
    total_size = 0
    directories = []
    directories.append(directory)

    while len(directories) > 0:
        next_dir = directories.pop()
        with os.scandir(next_dir) as it:
            for item in it:
                if item.is_file():
                    total_size += item.stat().st_size
                elif item.is_dir():
                    directories.append(item.path)
    
    return total_size

def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)
