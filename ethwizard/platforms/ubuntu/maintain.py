import subprocess
import httpx
import re

from packaging.version import parse as parse_version, Version

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog

from ethwizard.platforms.ubuntu.common import (
    log,
    save_state,
    quit_app,
    get_systemd_service_details
)

from ethwizard.constants import (
    CTX_SELECTED_EXECUTION_CLIENT,
    CTX_SELECTED_CONSENSUS_CLIENT,
    EXECUTION_CLIENT_GETH,
    CONSENSUS_CLIENT_LIGHTHOUSE,
    WIZARD_COMPLETED_STEP_ID,
    UNKNOWN_VALUE,
    GITHUB_REST_API_URL,
    GETH_LATEST_RELEASE,
    GITHUB_API_VERSION,
    GETH_SYSTEMD_SERVICE_NAME,
    MAINTENANCE_DO_NOTHING,
    MAINTENANCE_RESTART_SERVICE,
    MAINTENANCE_UPGRADE_CLIENT,
    MAINTENANCE_CHECK_AGAIN_SOON
)

def enter_maintenance(context):
    # Maintenance entry point for Ubuntu.
    # Maintenance is started after the wizard has completed.

    log.info(f'Entering maintenance mode. To be implemented.')

    if context is None:
        log.error('Missing context.')
        return False

    context = use_default_client(context)

    if context is None:
        log.error('Missing context.')
        return False
    
    return show_dashboard(context)

def show_dashboard(context):
    # Show simple dashboard

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]

    execution_client_details = get_execution_client_details(current_execution_client)
    if not execution_client_details:
        return False

    # Find out if we need to do maintenance for the execution client

    execution_client_details['next_step'] = MAINTENANCE_DO_NOTHING

    installed_version = execution_client_details['versions']['installed']
    if installed_version != UNKNOWN_VALUE:
        installed_version = parse_version(installed_version)
    running_version = execution_client_details['versions']['running']
    if running_version != UNKNOWN_VALUE:
        running_version = parse_version(running_version)
    available_version = execution_client_details['versions']['available']
    if available_version != UNKNOWN_VALUE:
        available_version = parse_version(available_version)
    latest_version = execution_client_details['versions']['latest']
    if latest_version != UNKNOWN_VALUE:
        latest_version = parse_version(latest_version)

    # If the available version is older than the latest one, we need to check again soon
    # It simply means that the updated build is not available yet for installing

    if is_version(latest_version) and is_version(available_version):
        if available_version < latest_version:
            execution_client_details['next_step'] = MAINTENANCE_CHECK_AGAIN_SOON

    # If the running version is older than the installed one, we need to restart the service

    if is_version(installed_version) and is_version(running_version):
        if running_version < installed_version:
            execution_client_details['next_step'] = MAINTENANCE_RESTART_SERVICE

    # If the installed version is older than the available one, we need to upgrade the client

    if is_version(installed_version) and is_version(available_version):
        if installed_version < available_version:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT

    print('Geth details:')
    print(execution_client_details)

    return True

def is_version(value):
    # Return true if this is a packaging version
    return isinstance(value, Version)

def get_execution_client_details(execution_client):
    # Get the details shown on the dashboard for the execution client

    details = {
        'service': {
            'found': False,
            'load': UNKNOWN_VALUE,
            'active': UNKNOWN_VALUE,
            'sub': UNKNOWN_VALUE
        },
        'versions': {
            'installed': UNKNOWN_VALUE,
            'running': UNKNOWN_VALUE,
            'available': UNKNOWN_VALUE,
            'latest': UNKNOWN_VALUE
        }
    }

    if execution_client == EXECUTION_CLIENT_GETH:
        
        # Check for existing systemd service
        geth_service_exists = False
        geth_service_name = GETH_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(geth_service_name)

        if service_details['LoadState'] == 'loaded':
            geth_service_exists = True
        
        if not geth_service_exists:
            return details
        
        details['service']['found'] = True
        details['service']['load'] = service_details['LoadState']
        details['service']['active'] = service_details['ActiveState']
        details['service']['sub'] = service_details['SubState']

        details['versions']['installed'] = get_geth_installed_version()
        details['versions']['running'] = get_geth_running_version()
        details['versions']['available'] = get_geth_available_version()
        details['versions']['latest'] = get_geth_latest_version()

        return details

    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False

def get_geth_installed_version():
    # Get the installed version for Geth

    log.info('Getting Geth installed version...')

    process_result = subprocess.run(['geth', 'version'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from geth. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Version: (?P<version>[^-]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Geth installed version.')
        return UNKNOWN_VALUE
    
    installed_version = result.group('version')

    log.info(f'Geth installed version is {installed_version}')

    return installed_version

def get_geth_running_version():
    # Get the running version for Geth

    log.info('Getting Geth running version...')

    local_geth_jsonrpc_url = 'http://127.0.0.1:8545'
    request_json = {
        'jsonrpc': '2.0',
        'method': 'web3_clientVersion',
        'id': 67
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Geth. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_geth_jsonrpc_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'result' not in response_json:
        log.error(f'Unexpected JSON response from {local_geth_jsonrpc_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['result']

    # Version agent should look like: Geth/v1.10.12-stable-6c4dc6c3/linux-amd64/go1.17.2
    result = re.search(r'Geth/v(?P<version>[^-/]+)(-(?P<stable>[^-/]+))?(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Geth version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Geth running version is {running_version}')

    return running_version

def get_geth_available_version():
    # Get the available version for Geth, potentially for update

    log.info('Getting Geth available version...')

    subprocess.run(['apt', '-y', 'update'])
    process_result = subprocess.run(['apt-cache', 'policy', 'geth'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from apt-cache. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Candidate: (?P<version>[^\+]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Geth candidate version.')
        return UNKNOWN_VALUE
    
    available_version = result.group('version')

    log.info(f'Geth available version is {available_version}')

    return available_version

def get_geth_latest_version():
    # Get the latest stable version for Geth, potentially not available yet for update

    log.info('Getting Geth latest version...')

    geth_gh_release_url = GITHUB_REST_API_URL + GETH_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(geth_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Geth. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Geth. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Geth.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Geth version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Geth latest version is {latest_version}')

    return latest_version

def use_default_client(context):
    # Set the default clients in context if they are not provided

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

    updated_context = False

    if selected_execution_client not in context:
        context[selected_execution_client] = EXECUTION_CLIENT_GETH
        updated_context = True
    
    if selected_consensus_client not in context:
        context[selected_consensus_client] = CONSENSUS_CLIENT_LIGHTHOUSE
        updated_context = True

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return None

    return context