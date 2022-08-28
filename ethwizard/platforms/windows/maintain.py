import subprocess
import httpx
import re
import time
import os
import shlex

from pathlib import Path

from packaging.version import parse as parse_version, Version

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog

from ethwizard.platforms.common import (
    select_fee_recipient_address,
    get_geth_running_version,
    get_geth_latest_version
)

from ethwizard.platforms.windows.common import (
    save_state,
    log,
    quit_app,
    get_service_details,
    get_nssm_binary
)

from ethwizard.constants import (
    CTX_SELECTED_EXECUTION_CLIENT,
    CTX_SELECTED_CONSENSUS_CLIENT,
    CTX_SELECTED_NETWORK,
    CTX_SELECTED_DIRECTORY,
    EXECUTION_CLIENT_GETH,
    CONSENSUS_CLIENT_TEKU,
    WIZARD_COMPLETED_STEP_ID,
    UNKNOWN_VALUE,
    MAINTENANCE_DO_NOTHING,
    MIN_CLIENT_VERSION_FOR_MERGE,
    MAINTENANCE_START_SERVICE,
    MAINTENANCE_RESTART_SERVICE,
    MAINTENANCE_CONFIG_CLIENT_MERGE,
    MAINTENANCE_UPGRADE_CLIENT,
    MAINTENANCE_UPGRADE_CLIENT_MERGE,
    MAINTENANCE_REINSTALL_CLIENT,
    WINDOWS_SERVICE_RUNNING,
    BN_VERSION_EP,
    GITHUB_REST_API_URL,
    GITHUB_API_VERSION,
    TEKU_LATEST_RELEASE
)

def enter_maintenance(context):
    # Maintenance entry point for Windows.
    # Maintenance is started after the wizard has completed.

    log.info(f'Entering maintenance mode. To be implemented.')

    if context is None:
        log.error('Missing context.')

    context = use_default_client(context)

    if context is None:
        log.error('Missing context.')

    return show_dashboard(context)

def show_dashboard(context):
    # Show simple dashboard

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
    selected_network = CTX_SELECTED_NETWORK
    selected_directory = CTX_SELECTED_DIRECTORY

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]
    current_network = context[selected_network]
    current_directory = context[selected_directory]

    # Get execution client details

    execution_client_details = get_execution_client_details(current_directory,
        current_execution_client)
    if not execution_client_details:
        log.error('Unable to get execution client details.')
        return False

    # Find out if we need to do maintenance for the execution client

    execution_client_details['next_step'] = MAINTENANCE_DO_NOTHING

    installed_version = execution_client_details['versions']['installed']
    if installed_version != UNKNOWN_VALUE:
        installed_version = parse_version(installed_version)
    running_version = execution_client_details['versions']['running']
    if running_version != UNKNOWN_VALUE:
        running_version = parse_version(running_version)
    latest_version = execution_client_details['versions']['latest']
    if latest_version != UNKNOWN_VALUE:
        latest_version = parse_version(latest_version)
    
    # Merge tests for execution client
    merge_ready_exec_version = parse_version(
        MIN_CLIENT_VERSION_FOR_MERGE[current_network][current_execution_client])

    is_installed_exec_merge_ready = False
    if is_version(installed_version) and is_version(merge_ready_exec_version):
        if installed_version >= merge_ready_exec_version:
            is_installed_exec_merge_ready = True

    is_latest_exec_merge_ready = False
    if is_version(latest_version) and is_version(merge_ready_exec_version):
        if latest_version >= merge_ready_exec_version:
            is_latest_exec_merge_ready = True

    # If the service is not running, we need to start it

    if not execution_client_details['service']['running']:
        execution_client_details['next_step'] = MAINTENANCE_START_SERVICE

    # If the running version is older than the installed one, we need to restart the service

    if is_version(installed_version) and is_version(running_version):
        if running_version < installed_version:
            execution_client_details['next_step'] = MAINTENANCE_RESTART_SERVICE

    # If the installed version is merge ready but the client is not configured for the merge,
    # we need to configure the client for the merge

    if is_version(installed_version):
        if is_installed_exec_merge_ready and not execution_client_details['is_merge_configured']:
            execution_client_details['next_step'] = MAINTENANCE_CONFIG_CLIENT_MERGE

    # If the installed version is older than the available one, we need to upgrade the client

    if is_version(installed_version) and is_version(latest_version):
        if installed_version < latest_version:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT
        
        # If the next version is merge ready and we are not configured yet, we need to upgrade and
        # configure the client

        if is_latest_exec_merge_ready and not execution_client_details['is_merge_configured']:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT_MERGE

    # If the service is not installed or found, we need to reinstall the client

    if not execution_client_details['service']['found']:
        execution_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # Get consensus client details

    consensus_client_details = get_consensus_client_details(current_directory,
        current_consensus_client)
    if not consensus_client_details:
        log.error('Unable to get consensus client details.')
        return False

    # Find out if we need to do maintenance for the consensus client

    consensus_client_details['next_step'] = MAINTENANCE_DO_NOTHING

    installed_version = consensus_client_details['versions']['installed']
    if installed_version != UNKNOWN_VALUE:
        installed_version = parse_version(installed_version)
    running_version = consensus_client_details['versions']['running']
    if running_version != UNKNOWN_VALUE:
        running_version = parse_version(running_version)
    latest_version = consensus_client_details['versions']['latest']
    if latest_version != UNKNOWN_VALUE:
        latest_version = parse_version(latest_version)
    
    # Merge tests for consensus client
    merge_ready_cons_version = parse_version(
        MIN_CLIENT_VERSION_FOR_MERGE[current_network][current_consensus_client])

    is_installed_cons_merge_ready = False
    if is_version(installed_version) and is_version(merge_ready_cons_version):
        if installed_version >= merge_ready_cons_version:
            is_installed_cons_merge_ready = True

    is_latest_cons_merge_ready = False
    if is_version(latest_version) and is_version(merge_ready_cons_version):
        if latest_version >= merge_ready_cons_version:
            is_latest_cons_merge_ready = True

    # If the service is not running, we need to start it

    if not consensus_client_details['bn_service']['running']:
        consensus_client_details['next_step'] = MAINTENANCE_START_SERVICE

    if not consensus_client_details['vc_service']['running']:
        consensus_client_details['next_step'] = MAINTENANCE_START_SERVICE

    # If the running version is older than the installed one, we need to restart the services

    if is_version(installed_version) and is_version(running_version):
        if running_version < installed_version:
            consensus_client_details['next_step'] = MAINTENANCE_RESTART_SERVICE

    # If the installed version is merge ready but the client is not configured for the merge,
    # we need to configure the client for the merge

    if is_version(installed_version):
        if is_installed_cons_merge_ready and (
            not consensus_client_details['is_bn_merge_configured'] or
            not consensus_client_details['is_vc_merge_configured']):
            consensus_client_details['next_step'] = MAINTENANCE_CONFIG_CLIENT_MERGE

    # If the installed version is older than the latest one, we need to upgrade the client

    if is_version(installed_version) and is_version(latest_version):
        if installed_version < latest_version:
            consensus_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT
        
        # If the next version is merge ready and we are not configured yet, we need to upgrade and
        # configure the client

        if is_latest_cons_merge_ready and (
            not consensus_client_details['is_bn_merge_configured'] or
            not consensus_client_details['is_vc_merge_configured']):
            consensus_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT_MERGE

    # If the service is not installed or found, we need to reinstall the client

    if (not consensus_client_details['bn_service']['found'] or
        not consensus_client_details['vc_service']['found']):
        consensus_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # We only need to do maintenance if either the execution or the consensus client needs
    # maintenance.

    maintenance_needed = (
        execution_client_details['next_step'] != MAINTENANCE_DO_NOTHING or
        consensus_client_details['next_step'] != MAINTENANCE_DO_NOTHING)

    # Build the dashboard with the details we have

    maintenance_tasks_description = {
        MAINTENANCE_DO_NOTHING: 'Nothing to perform here. Everything is good.',
        MAINTENANCE_RESTART_SERVICE: 'Service needs to be restarted.',
        MAINTENANCE_UPGRADE_CLIENT: 'Client needs to be upgraded.',
        MAINTENANCE_UPGRADE_CLIENT_MERGE: (
            'Client needs to be upgraded and configured for the merge.'),
        MAINTENANCE_CONFIG_CLIENT_MERGE: 'Client needs to be configured for the merge.',
        MAINTENANCE_START_SERVICE: 'Service needs to be started.',
        MAINTENANCE_REINSTALL_CLIENT: 'Client needs to be reinstalled.',
    }

    buttons = [
        ('Quit', False),
    ]

    maintenance_message = 'Nothing is needed in terms of maintenance.'

    if maintenance_needed:
        buttons = [
            ('Maintain', 1),
            ('Quit', False),
        ]

        maintenance_message = 'Some maintenance tasks are pending. Select maintain to perform them.'

    ec_section = (f'<b>Geth</b> details (I: {execution_client_details["versions"]["installed"]}, '
        f'R: {execution_client_details["versions"]["running"]}, '
        f'L: {execution_client_details["versions"]["latest"]})\n'
        f'Service is running: {execution_client_details["service"]["running"]}\n'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(execution_client_details["next_step"], UNKNOWN_VALUE)}')

    cc_services = f'Running services - Beacon node: {consensus_client_details["bn_service"]["running"]}, Validator client: {consensus_client_details["vc_service"]["running"]}\n'
    if consensus_client_details['unified_service']:
        cc_services = f'Service is running: {consensus_client_details["bn_service"]["running"]}\n'

    cc_section = (f'<b>Teku</b> details (I: {consensus_client_details["versions"]["installed"]}, '
        f'R: {consensus_client_details["versions"]["running"]}, '
        f'L: {consensus_client_details["versions"]["latest"]})\n'
        f'{cc_services}'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(consensus_client_details["next_step"], UNKNOWN_VALUE)}')

    result = button_dialog(
        title='Maintenance Dashboard',
        text=(HTML(
f'''
Here are some details about your Ethereum clients.

{ec_section}

{cc_section}

{maintenance_message}

Versions legend - I: Installed, R: Running, L: Latest
'''             )),
        buttons=buttons
    ).run()

    if not result:
        return False
    
    if result == 1:
        if perform_maintenance(current_execution_client, execution_client_details,
            current_consensus_client, consensus_client_details):
            return show_dashboard(context)
        else:
            log.error('We could not perform all the maintenance tasks.')
            return False

def is_version(value):
    # Return true if this is a packaging version
    return isinstance(value, Version)

def is_service_running(service_details):
    # Return true if this Windows service is running
    return service_details['status'] == WINDOWS_SERVICE_RUNNING

def get_execution_client_details(base_directory, execution_client):
    # Get the details for the current execution client

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    if execution_client == EXECUTION_CLIENT_GETH:

        details = {
            'service': {
                'found': False,
                'status': UNKNOWN_VALUE,
                'binary': UNKNOWN_VALUE,
                'parameters': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE
            },
            'versions': {
                'installed': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE,
                'latest': UNKNOWN_VALUE
            },
            'exec': {
                'path': UNKNOWN_VALUE,
                'argv': []
            },
            'is_merge_configured': UNKNOWN_VALUE
        }
        
        # Check for existing service
        geth_service_exists = False
        geth_service_name = 'geth'

        service_details = get_service_details(nssm_binary, geth_service_name)

        if service_details is not None:
            geth_service_exists = True
        
        if not geth_service_exists:
            return details

        details['service']['found'] = True
        details['service']['status'] = service_details['status']
        details['service']['binary'] = service_details['install']
        details['service']['parameters'] = service_details['parameters']['AppParameters']
        details['service']['running'] = is_service_running(service_details)

        details['versions']['installed'] = get_geth_installed_version(base_directory)
        details['versions']['running'] = get_geth_running_version(log)
        details['versions']['latest'] = get_geth_latest_version(log)

        details['exec']['path'] = service_details['install']
        details['exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        for arg in details['exec']['argv']:
            if arg.lower().startswith('--authrpc.jwtsecret'):
                details['is_merge_configured'] = True
                break
        
        if details['is_merge_configured'] == UNKNOWN_VALUE:
            details['is_merge_configured'] = False

        return details

    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False

def get_geth_installed_version(base_directory):
    # Get the installed version for Geth

    log.info('Getting Geth installed version...')

    geth_path = base_directory.joinpath('bin', 'geth.exe')

    process_result = subprocess.run([geth_path, 'version'], capture_output=True,
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

def get_consensus_client_details(base_directory, consensus_client):
    # Get the details for the current consensus client

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    if consensus_client == CONSENSUS_CLIENT_TEKU:

        details = {
            'unified_service': True,
            'bn_service': {
                'found': False,
                'status': UNKNOWN_VALUE,
                'binary': UNKNOWN_VALUE,
                'parameters': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE
            },
            'vc_service': {
                'found': False,
                'status': UNKNOWN_VALUE,
                'binary': UNKNOWN_VALUE,
                'parameters': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE
            },
            'versions': {
                'installed': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE,
                'latest': UNKNOWN_VALUE
            },
            'bn_exec': {
                'path': UNKNOWN_VALUE,
                'argv': []
            },
            'vc_exec': {
                'path': UNKNOWN_VALUE,
                'argv': []
            },
            'is_bn_merge_configured': UNKNOWN_VALUE,
            'is_vc_merge_configured': UNKNOWN_VALUE
        }
        
        # Check for existing service
        teku_service_exists = False
        teku_service_name = 'teku'

        service_details = get_service_details(nssm_binary, teku_service_name)

        if service_details is not None:
            teku_service_exists = True
        
        if not teku_service_exists:
            return details

        details['bn_service']['found'] = True
        details['bn_service']['status'] = service_details['status']
        details['bn_service']['binary'] = service_details['install']
        details['bn_service']['parameters'] = service_details['parameters']['AppParameters']
        details['bn_service']['running'] = is_service_running(service_details)

        details['bn_exec']['path'] = service_details['install']
        details['bn_exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        details['vc_service']['found'] = details['bn_service']['found']
        details['vc_service']['status'] = details['bn_service']['status']
        details['vc_service']['binary'] = details['bn_service']['binary']
        details['vc_service']['parameters'] = details['bn_service']['parameters']
        details['vc_service']['running'] = details['bn_service']['running']

        details['vc_exec']['path'] = details['bn_exec']['path']
        details['vc_exec']['argv'] = details['bn_exec']['argv']

        execution_jwt_flag_found = False
        execution_endpoint_flag_found = False
        for arg in details['bn_exec']['argv']:
            if arg.lower().startswith('--ee-jwt-secret-file'):
                execution_jwt_flag_found = True
            if arg.lower().startswith('--ee-endpoint'):
                execution_endpoint_flag_found = True
            if execution_jwt_flag_found and execution_endpoint_flag_found:
                break
        
        details['is_bn_merge_configured'] = (
            execution_jwt_flag_found and execution_endpoint_flag_found)
        
        for arg in details['vc_exec']['argv']:
            if arg.lower().startswith('--validators-proposer-default-fee-recipient'):
                details['is_vc_merge_configured'] = True
                break
        
        if details['is_vc_merge_configured'] == UNKNOWN_VALUE:
            details['is_vc_merge_configured'] = False

        details['versions']['installed'] = get_teku_installed_version(base_directory)
        details['versions']['running'] = get_teku_running_version()
        details['versions']['latest'] = get_teku_latest_version()

        return details

    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

def get_teku_installed_version(base_directory):
    # Get the installed version for Teku

    log.info('Getting Teku installed version...')

    teku_path = base_directory.joinpath('bin', 'teku')
    teku_batch_file = teku_path.joinpath('bin', 'teku.bat')

    teku_found = False
    teku_version = UNKNOWN_VALUE

    java_home = base_directory.joinpath('bin', 'jre')

    if teku_batch_file.is_file():
        try:
            env = os.environ.copy()
            env['JAVA_HOME'] = str(java_home)

            process_result = subprocess.run([
                str(teku_batch_file), '--version'
                ], capture_output=True, text=True, env=env)
            
            if process_result.returncode != 0:
                log.error(f'Unexpected return code from Teku. Return code: '
                    f'{process_result.returncode}')
                return UNKNOWN_VALUE

            teku_found = True

            process_output = process_result.stdout
            result = re.search(r'teku/(?P<version>[^/]+)', process_output)
            if result:
                teku_version = result.group('version').strip()
            else:
                log.error(f'We could not parse Teku version from output: {process_result.stdout}')

        except FileNotFoundError:
            pass

    if teku_found:
        log.info(f'Teku installed version is {teku_version}')

        return teku_version
    
    return UNKNOWN_VALUE

def get_teku_running_version():
    # Get the running version for Teku

    log.info('Getting Teku running version...')

    local_teku_bn_version_url = 'http://127.0.0.1:5051' + BN_VERSION_EP

    try:
        response = httpx.get(local_teku_bn_version_url)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Teku. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_teku_bn_version_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'data' not in response_json or 'version' not in response_json['data']:
        log.error(f'Unexpected JSON response from {local_teku_bn_version_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['data']['version']

    # Version agent should look like: teku/v22.8.1/windows-x86_64/-eclipseadoptium-openjdk64bitservervm-java-17
    result = re.search(r'teku/v(?P<version>[^-/]+)(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Teku version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Teku running version is {running_version}')

    return running_version

def get_teku_latest_version():
    # Get the latest version for Teku

    log.info('Getting Teku latest version...')

    lighthouse_gh_release_url = GITHUB_REST_API_URL + TEKU_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(lighthouse_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Teku. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Teku. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Teku.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Teku version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Teku latest version is {latest_version}')

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
        context[selected_consensus_client] = CONSENSUS_CLIENT_TEKU
        updated_context = True

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return None

    return context

def perform_maintenance(execution_client, execution_client_details, consensus_client,
    consensus_client_details):
    # TODO: Perform all the maintenance tasks

    return False