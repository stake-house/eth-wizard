import subprocess
import httpx
import re
import time
import os
import shlex
import hashlib
import shutil

from pathlib import Path

from urllib.parse import urljoin, urlparse

from defusedxml import ElementTree

from dateutil.parser import parse as dateparse

from zipfile import ZipFile

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
    get_nssm_binary,
    is_stable_windows_amd64_archive,
    install_gpg,
    set_service_param,
    setup_jwt_token_file
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
    MAINTENANCE_IMPROVE_TIMEOUT,
    WINDOWS_SERVICE_RUNNING,
    BN_VERSION_EP,
    GITHUB_REST_API_URL,
    GITHUB_API_VERSION,
    TEKU_LATEST_RELEASE,
    GETH_STORE_BUILDS_PARAMS,
    GETH_STORE_BUILDS_URL,
    GETH_BUILDS_BASE_URL,
    PGP_KEY_SERVERS,
    GETH_WINDOWS_PGP_KEY_ID,
    NETWORK_GOERLI,
    CTX_EXECUTION_IMPROVED_SERVICE_TIMEOUT,
    CTX_CONSENSUS_IMPROVED_SERVICE_TIMEOUT
)

def enter_maintenance(context):
    # Maintenance entry point for Windows.
    # Maintenance is started after the wizard has completed.

    log.info(f'Entering maintenance mode.')

    if context is None:
        log.error('Missing context.')

    context = use_default_values(context)

    if context is None:
        log.error('Missing context.')

    return show_dashboard(context)

def show_dashboard(context):
    # Show simple dashboard

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
    selected_network = CTX_SELECTED_NETWORK
    selected_directory = CTX_SELECTED_DIRECTORY
    execution_improved_service_timeout = CTX_EXECUTION_IMPROVED_SERVICE_TIMEOUT
    consensus_improved_service_timeout = CTX_CONSENSUS_IMPROVED_SERVICE_TIMEOUT

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]
    current_network = context[selected_network]
    current_directory = context[selected_directory]
    current_execution_improved_service_timeout = context[execution_improved_service_timeout]
    current_consensus_improved_service_timeout = context[consensus_improved_service_timeout]

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

    # If the service do not have improved shutdown timeout, we need to improve it
    if not current_execution_improved_service_timeout:
        execution_client_details['next_step'] = MAINTENANCE_IMPROVE_TIMEOUT

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

    # If the service do not have improved shutdown timeout, we need to improve it
    if not current_consensus_improved_service_timeout:
        consensus_client_details['next_step'] = MAINTENANCE_IMPROVE_TIMEOUT

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
        MAINTENANCE_IMPROVE_TIMEOUT: 'Improve service shutdown timeout',
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
        maintenance_result = perform_maintenance(current_directory, current_execution_client,
            execution_client_details, current_consensus_client, consensus_client_details, context)
        if maintenance_result:
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

    teku_gh_release_url = GITHUB_REST_API_URL + TEKU_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(teku_gh_release_url, headers=headers,
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

def use_default_values(context):
    # Set the default values in context if they are not provided

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
    selected_network = CTX_SELECTED_NETWORK
    execution_improved_service_timeout = CTX_EXECUTION_IMPROVED_SERVICE_TIMEOUT
    consensus_improved_service_timeout = CTX_CONSENSUS_IMPROVED_SERVICE_TIMEOUT

    updated_context = False

    if selected_execution_client not in context:
        context[selected_execution_client] = EXECUTION_CLIENT_GETH
        updated_context = True
    
    if selected_consensus_client not in context:
        context[selected_consensus_client] = CONSENSUS_CLIENT_TEKU
        updated_context = True
    
    if selected_network in context and context[selected_consensus_client] == 'prater':
        context[selected_consensus_client] = NETWORK_GOERLI
        updated_context = True
    
    if execution_improved_service_timeout not in context:
        context[execution_improved_service_timeout] = False
        updated_context = True
    
    if consensus_improved_service_timeout not in context:
        context[consensus_improved_service_timeout] = False
        updated_context = True

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return None

    return context

def perform_maintenance(base_directory, execution_client, execution_client_details,
    consensus_client, consensus_client_details, context):
    # Perform all the maintenance tasks

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False
    
    updated_context = False

    if execution_client == EXECUTION_CLIENT_GETH:
        # Geth maintenance tasks
        geth_service_name = 'geth'

        if execution_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Geth service...')

            subprocess.run([str(nssm_binary), 'restart', geth_service_name])

        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_geth(base_directory, nssm_binary):
                log.error('We could not upgrade the Geth client.')
                return False
        
        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            if not config_geth_merge(base_directory, nssm_binary, execution_client_details):
                log.error('We could not configure Geth for the merge.')
                return False
            
            if not upgrade_geth(base_directory, nssm_binary):
                log.error('We could not upgrade the Geth client.')
                return False
    
        elif execution_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            if not config_geth_merge(base_directory, nssm_binary, execution_client_details):
                log.error('We could not configure Geth for the merge.')
                return False
            
            log.info('Restarting Geth service...')

            subprocess.run([str(nssm_binary), 'restart', geth_service_name])

        elif execution_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Geth service...')

            subprocess.run([str(nssm_binary), 'start', geth_service_name])

        elif execution_client_details['next_step'] == MAINTENANCE_IMPROVE_TIMEOUT:
            log.info('Configuring Geth service to have a 180 seconds timeout on shutdown...')

            if not set_service_param(nssm_binary, geth_service_name, 'AppStopMethodConsole', '180000'):
                return False
            if not set_service_param(nssm_binary, geth_service_name, 'AppStopMethodWindow', '180000'):
                return False
            if not set_service_param(nssm_binary, geth_service_name, 'AppStopMethodThreads', '180000'):
                return False
            
            execution_improved_service_timeout = CTX_EXECUTION_IMPROVED_SERVICE_TIMEOUT
            context[execution_improved_service_timeout] = True
            updated_context = True

        elif execution_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warning('TODO: Reinstalling client is to be implemented.')
    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False
    
    if consensus_client == CONSENSUS_CLIENT_TEKU:
        # Teku maintenance tasks
        teku_service_name = 'teku'

        if consensus_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Teku service...')

            subprocess.run([str(nssm_binary), 'restart', teku_service_name])

        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_teku(base_directory, nssm_binary):
                log.error('We could not upgrade the Teku client.')
                return False
        
        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            if not config_teku_merge(base_directory, nssm_binary, consensus_client_details):
                log.error('We could not configure Teku for the merge.')
                return False

            if not upgrade_teku(base_directory, nssm_binary):
                log.error('We could not upgrade the Teku client.')
                return False
    
        elif consensus_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            if not config_teku_merge(base_directory, nssm_binary, consensus_client_details):
                log.error('We could not configure Teku for the merge.')
                return False
            
            log.info('Restarting Teku service...')

            subprocess.run([str(nssm_binary), 'restart', teku_service_name])
            
        elif consensus_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Teku service...')

            subprocess.run([str(nssm_binary), 'start', teku_service_name])
        
        elif consensus_client_details['next_step'] == MAINTENANCE_IMPROVE_TIMEOUT:
            log.info('Configuring Teku service to have a 180 seconds timeout on shutdown...')

            if not set_service_param(nssm_binary, teku_service_name, 'AppStopMethodConsole', '1500'):
                return False
            if not set_service_param(nssm_binary, teku_service_name, 'AppStopMethodWindow', '180000'):
                return False
            if not set_service_param(nssm_binary, teku_service_name, 'AppStopMethodThreads', '180000'):
                return False
            
            consensus_improved_service_timeout = CTX_CONSENSUS_IMPROVED_SERVICE_TIMEOUT
            context[consensus_improved_service_timeout] = True
            updated_context = True

        elif consensus_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warning('TODO: Reinstalling client is to be implemented.')
    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return False

    return context

def upgrade_geth(base_directory, nssm_binary):
    # Upgrade the Geth client
    log.info('Upgrading Geth client...')

    # Get list of geth releases/builds from their store
    next_marker = None
    page_end_found = False

    windows_builds = []

    try:
        log.info('Getting geth builds...')
        while not page_end_found:
            params = GETH_STORE_BUILDS_PARAMS.copy()
            if next_marker is not None:
                params['marker'] = next_marker

            response = httpx.get(GETH_STORE_BUILDS_URL, params=params, follow_redirects=True)

            if response.status_code != 200:
                log.error(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\n'
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
        log.error(f'Cannot connect to geth builds URL {GETH_STORE_BUILDS_URL}.\n'
            f'Exception {exception}')
        return False

    if len(windows_builds) <= 0:
        log.error('No geth builds found on geth store. We cannot continue.')
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
            log.info(f'Downloading geth archive {latest_build["name"]}...')
            with httpx.stream('GET', latest_build_url, follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'Cannot download geth archive {latest_build_url}.\n'
                        f'Unexpected status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading geth archive. Exception {exception}')
        return False

    geth_archive_sig_path = download_path.joinpath(latest_build['name'] + '.asc')
    if geth_archive_sig_path.is_file():
        geth_archive_sig_path.unlink()

    latest_build_sig_url = urljoin(GETH_BUILDS_BASE_URL, latest_build['name'] + '.asc')

    try:
        with open(geth_archive_sig_path, 'wb') as binary_file:
            log.info(f'Downloading geth archive signature {latest_build["name"]}.asc...')
            with httpx.stream('GET', latest_build_sig_url,
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'Cannot download geth archive signature {latest_build_sig_url}.\n'
                        f'Unexpected status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading geth archive signature. Exception {exception}')
        return False

    if not install_gpg(base_directory):
        return False
    
    # Verify PGP signature
    gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

    command_line = [str(gpg_binary_path), '--list-keys', '--with-colons', GETH_WINDOWS_PGP_KEY_ID]
    process_result = subprocess.run(command_line)
    pgp_key_found = process_result.returncode == 0

    if not pgp_key_found:

        retry_index = 0
        retry_count = 15

        key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
        log.info(f'Downloading Geth Windows Builder PGP key from {key_server} ...')
        command_line = [str(gpg_binary_path), '--keyserver', key_server,
            '--recv-keys', GETH_WINDOWS_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        if process_result.returncode != 0:
            # GPG failed to download Geth Windows Builder PGP key, let's wait and retry a few times
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                delay = 5
                log.warning(f'GPG failed to download the PGP key. We will wait {delay} seconds '
                    f'and try again from a different server.')
                time.sleep(delay)

                key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
                log.info(f'Downloading Geth Windows Builder PGP key from {key_server} ...')
                command_line = [str(gpg_binary_path), '--keyserver', key_server,
                    '--recv-keys', GETH_WINDOWS_PGP_KEY_ID]

                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            log.error(
f'''
We failed to download the Geth Windows Builder PGP key to verify the geth
archive after {retry_count} retries.
'''
            )
            return False
    
    process_result = subprocess.run([
        str(gpg_binary_path), '--verify', str(geth_archive_sig_path)])
    if process_result.returncode != 0:
        log.error('The geth archive signature is wrong. We\'ll stop here to protect you.')
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
        log.error('The geth binary was not found in the archive. We cannot continue.')
        return False

    geth_service_name = 'geth'
    log.info('Stoping Geth service...')
    subprocess.run([str(nssm_binary), 'stop', geth_service_name])

    # Move geth back into bin directory
    target_geth_binary_path = bin_path.joinpath('geth.exe')
    if target_geth_binary_path.is_file():
        target_geth_binary_path.unlink()
    
    geth_extracted_binary.rename(target_geth_binary_path)

    geth_extracted_binary.parent.rmdir()

    log.info('Starting Geth service...')
    subprocess.run([str(nssm_binary), 'start', geth_service_name])

    return True

def config_geth_merge(base_directory, nssm_binary, client_details):
    # Configure Geth for the merge
    log.info('Configuring Geth for the merge...')

    jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
    jwt_token_path = jwt_token_dir.joinpath('jwttoken')

    log.info('Creating JWT token file if needed...')
    if not setup_jwt_token_file(base_directory):
        log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
        )

        return False
    
    geth_service_name = 'geth'

    has_jwt_config = False
    geth_arguments = client_details['exec']['argv']

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(geth_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = f'"{jwt_token_path}"'
            break
        elif arg.lower().startswith('--authrpc.jwtsecret'):
            has_jwt_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--authrpc.jwtsecret="{jwt_token_path}"'
                break
            else:
                replace_next = True

    if not has_jwt_config:
        log.info('Adding JWT token configuration to Geth...')

        geth_arguments.append('--authrpc.jwtsecret')
        geth_arguments.append(f'"{jwt_token_path}"')
    else:
        log.warning('Geth was already configured with a JWT token. We will try to update or make '
            'sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for JWT token argument.')
            return False
        
        geth_arguments[replaced_index] = replaced_arg


    if not set_service_param(nssm_binary, geth_service_name, 'AppParameters', geth_arguments):
        return False

    return True

def upgrade_teku(base_directory, nssm_binary):
    # Upgrade the Teku client
    log.info('Upgrading Teku client...')

    teku_path = base_directory.joinpath('bin', 'teku')
    teku_batch_file = teku_path.joinpath('bin', 'teku.bat')

    java_home = base_directory.joinpath('bin', 'jre')

    # Getting latest Teku release files
    teku_gh_release_url = GITHUB_REST_API_URL + TEKU_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(teku_gh_release_url, headers=headers, follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Github. Exception {exception}')
        return False

    if response.status_code != 200:
        log.error(f'Github returned error code. Status code {response.status_code}')
        return False
    
    release_json = response.json()

    if 'body' not in release_json:
        log.error('Unexpected response from github release. We cannot continue.')
        return False
    
    release_desc = release_json['body']

    zip_url = None
    zip_sha256 = None

    result = re.search(r'\[zip\]\((?P<url>[^\)]+)\)\s*\(\s*sha256\s*:?\s*`(?P<sha256>[^`]+)`\s*\)',
        release_desc)
    if result:
        zip_url = result.group('url')
        if zip_url is not None:
            zip_url = zip_url.strip()
        
        zip_sha256 = result.group('sha256')
        if zip_sha256 is not None:
            zip_sha256 = zip_sha256.strip()

    if zip_url is None or zip_sha256 is None:
        log.error('Could not find binary distribution zip or checksum in Github release body. '
            'We cannot continue.')
        return False
    
    # Downloading latest Teku binary distribution archive
    download_path = base_directory.joinpath('downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    url_file_name = urlparse(zip_url).path.split('/')[-1]

    teku_archive_path = download_path.joinpath(url_file_name)
    teku_archive_hash = hashlib.sha256()
    if teku_archive_path.is_file():
        teku_archive_path.unlink()

    keep_retrying = True

    retry_index = 0
    retry_count = 6
    retry_delay = 30
    retry_delay_increase = 10
    last_exception = None
    last_status_code = None

    while keep_retrying and retry_index < retry_count:
        last_exception = None
        last_status_code = None
        try:
            with open(teku_archive_path, 'wb') as binary_file:
                log.info(f'Downloading teku archive {url_file_name}...')
                with httpx.stream('GET', zip_url, follow_redirects=True) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'Cannot download teku archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        last_status_code = http_stream.status_code

                        retry_index = retry_index + 1
                        log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
                        time.sleep(retry_delay)
                        retry_delay = retry_delay + retry_delay_increase
                        continue

                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        teku_archive_hash.update(data)
                
                keep_retrying = False

        except httpx.RequestError as exception:
            
            log.error(f'Exception while downloading teku archive. Exception {exception}')
            last_exception = exception

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue
    
    if keep_retrying:
        if last_exception is not None:
            result = button_dialog(
                title='Cannot download Teku archive',
                text=(
f'''
We could not download the teku archive. Here are some details for this
last test we tried to perform:

URL: {zip_url}
Method: GET
Exception: {last_exception}

We cannot proceed if we cannot download the teku archive. Make sure there
is no network issue when we try to connect to the Internet.
'''                 ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            return False
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot download Teku archive',
                text=(
f'''
We could not download the teku archive. Here are some details for this
last test we tried to perform:

URL: {zip_url}
Method: GET
Status code: {last_status_code}

We cannot proceed if we cannot download the teku archive. Make sure there
is no network issue when we try to connect to the Internet.
'''                 ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            return False

    # Verify checksum
    log.info('Verifying teku archive checksum...')
    teku_archive_hexdigest = teku_archive_hash.hexdigest()
    if teku_archive_hexdigest.lower() != zip_sha256.lower():
        log.error('Teku archive checksum does not match. We will stop here to protect you.')
        return False
    
    # Unzip teku archive
    archive_members = None

    log.info(f'Extracting teku archive {url_file_name}...')
    with ZipFile(teku_archive_path, 'r') as zip_file:
        archive_members = zip_file.namelist()
        zip_file.extractall(download_path)
    
    # Remove download leftovers
    teku_archive_path.unlink()

    if archive_members is None or len(archive_members) == 0:
        log.error('No files found in teku archive. We cannot continue.')
        return False
    
    teku_service_name = 'teku'
    subprocess.run([str(nssm_binary), 'stop', teku_service_name])

    # Move all those extracted files into their final destination
    if teku_path.is_dir():
        shutil.rmtree(teku_path)
    teku_path.mkdir(parents=True, exist_ok=True)

    archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

    with os.scandir(archive_extracted_dir) as it:
        for diritem in it:
            shutil.move(diritem.path, teku_path)
        
    # Make sure teku was installed properly
    teku_found = False
    if teku_batch_file.is_file():
        try:
            env = os.environ.copy()
            env['JAVA_HOME'] = str(java_home)

            process_result = subprocess.run([
                str(teku_batch_file), '--version'
                ], capture_output=True, text=True, env=env)
            teku_found = True

            process_output = process_result.stdout
            result = re.search(r'teku/(?P<version>[^/]+)', process_output)
            if result:
                teku_version = result.group('version').strip()

        except FileNotFoundError:
            pass

    if not teku_found:
        log.error(f'We could not find the teku binary distribution from the installed archive '
            f'in {teku_path}. We cannot continue.')
        return False
    else:
        log.info(f'Teku version {teku_version} installed.')
    
    subprocess.run([str(nssm_binary), 'start', teku_service_name])

    return True

def config_teku_merge(base_directory, nssm_binary, client_details):
    # Configure Teku for the merge
    log.info('Configuring Teku for the merge...')

    fee_recipient_address = select_fee_recipient_address()
    if not fee_recipient_address:
        log.error('No fee recipient address entered.')
        return False
    
    jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
    jwt_token_path = jwt_token_dir.joinpath('jwttoken')

    log.info('Creating JWT token file if needed...')
    if not setup_jwt_token_file(base_directory):
        log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
        )

        return False
    
    teku_service_name = 'teku'

    teku_arguments = client_details['bn_exec']['argv']

    # JWT token configuration (--ee-jwt-secret-file)
    has_jwt_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(teku_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = f'"{jwt_token_path}"'
            break
        elif arg.lower().startswith('--ee-jwt-secret-file'):
            has_jwt_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--ee-jwt-secret-file="{jwt_token_path}"'
                break
            else:
                replace_next = True

    if not has_jwt_config:
        log.info('Adding JWT token configuration to Teku...')

        teku_arguments.append(f'--ee-jwt-secret-file="{jwt_token_path}"')
    else:
        log.warning('Teku was already configured with a JWT token. We will try to update or make '
            'sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for JWT token argument.')
            return False
        
        teku_arguments[replaced_index] = replaced_arg

    # Fee Recipient address configuration (--validators-proposer-default-fee-recipient)
    has_fee_recipient_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(teku_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = fee_recipient_address
            break
        elif arg.lower().startswith('--validators-proposer-default-fee-recipient'):
            has_fee_recipient_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--validators-proposer-default-fee-recipient={fee_recipient_address}'
                break
            else:
                replace_next = True

    if not has_fee_recipient_config:
        log.info('Adding fee recipient address configuration to Teku...')

        teku_arguments.append(f'--validators-proposer-default-fee-recipient={fee_recipient_address}')
    else:
        log.warning('Teku was already configured with a fee recipient address. We will try to update '
            'or make sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for fee recipient address argument.')
            return False
        
        teku_arguments[replaced_index] = replaced_arg

    # Execution endpoint (--ee-endpoint)
    has_execution_endpoint_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(teku_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = 'http://127.0.0.1:8551'
            break
        elif arg.lower().startswith('--ee-endpoint'):
            has_execution_endpoint_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--ee-endpoint=http://127.0.0.1:8551'
                break
            else:
                replace_next = True

    if not has_execution_endpoint_config:
        log.info('Adding execution endpoint configuration to Teku...')

        teku_arguments.append(f'--ee-endpoint=http://127.0.0.1:8551')
    else:
        log.warning('Teku was already configured with an execution endpoint. We will try to update '
            'or make sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for execution endpoint argument.')
            return False
        
        teku_arguments[replaced_index] = replaced_arg

    # Remove any old eth1 endpoint configuration (--eth1-endpoint(s))
    has_eth1_endpoint_config = False

    remove_start = None
    remove_length = None

    for index, arg in enumerate(teku_arguments):
        if arg.lower().startswith('--eth1-endpoint'):
            has_eth1_endpoint_config = True
            if '=' in arg:
                remove_start = index
                remove_length = 1
            else:
                remove_start = index
                remove_length = 2
            break
    
    if has_eth1_endpoint_config:
        log.info('Removing old eth1 endpoint configuration from Teku...')

        if remove_start is None or remove_length is None:
            log.error('No remove start or length for eth1 endpoint argument.')
            return False

        del teku_arguments[remove_start:remove_start + remove_length]
    
    if not set_service_param(nssm_binary, teku_service_name, 'AppParameters', teku_arguments):
        return False

    return True