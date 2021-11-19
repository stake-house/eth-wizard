import subprocess
import httpx
import re

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
    WIZARD_COMPLETED_STEP_ID
)

def enter_maintenance(context):
    # Maintenance entry point for Ubuntu.
    # Maintenance is started after the wizard has completed.

    log.info(f'Entering maintenance mode.')

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

    print(execution_client_details)

    return True

def get_execution_client_details(execution_client):
    # Get the details shown on the dashboard for the execution client

    if execution_client == EXECUTION_CLIENT_GETH:
        
        # Check for existing systemd service
        geth_service_exists = False
        geth_service_name = 'geth.service'

        service_details = get_systemd_service_details(geth_service_name)

        if service_details['LoadState'] == 'loaded':
            geth_service_exists = True
        
        if not geth_service_exists:
            return (
f'''
Service not found.
'''
            ).strip()
        
        details = (
f'''
Service states - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
'''
        ).strip()

        geth_running_version = get_geth_running_version()
        geth_available_version = get_geth_available_version()

        print(f'Running {geth_running_version}, Available: {geth_available_version}')

        return details

    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False

def get_geth_running_version():
    # Get the running version for Geth

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
        return False

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_geth_jsonrpc_url}. Status code: '
            f'{response.status_code}')
        return False
    
    response_json = response.json()

    if 'result' not in response_json:
        log.error(f'Unexpected JSON response from {local_geth_jsonrpc_url}. result not found.')
        return False
    
    version_agent = response_json['result']

    # Version agent should look like: Geth/v1.10.12-stable-6c4dc6c3/linux-amd64/go1.17.2
    result = re.search(r'Geth/v(?P<version>[^-/]+)(-(?P<stable>[^-/]+))?(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Geth version.')
        return False

    return result.group('version')

def get_geth_available_version():
    # Get the available version for Geth, potentially for update

    subprocess.run(['apt', '-y', 'update'])
    process_result = subprocess.run(['apt-cache', 'policy', 'geth'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from apt-cache. Return code: '
            f'{process_result.returncode}')
        return False
    
    process_output = process_result.stdout
    result = re.search(r'Candidate: (?P<version>[^\+]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for candidate version.')
        return False
    
    return result.group('version')

def get_geth_latest_version():
    # Get the latest stable version for Geth, potentially not available yet for update
    pass

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