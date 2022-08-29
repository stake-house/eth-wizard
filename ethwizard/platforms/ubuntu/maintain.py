import subprocess
import httpx
import re
import time
import os

from packaging.version import parse as parse_version, Version

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog

from pathlib import Path

from ethwizard.platforms.common import (
    select_fee_recipient_address,
    get_geth_running_version,
    get_geth_latest_version
)

from ethwizard.platforms.ubuntu.common import (
    log,
    save_state,
    quit_app,
    get_systemd_service_details,
    is_package_installed,
    is_adx_supported,
    setup_jwt_token_file,
    is_ethereum_ppa_added
)

from ethwizard.constants import (
    CTX_SELECTED_EXECUTION_CLIENT,
    CTX_SELECTED_CONSENSUS_CLIENT,
    CTX_SELECTED_NETWORK,
    EXECUTION_CLIENT_GETH,
    CONSENSUS_CLIENT_LIGHTHOUSE,
    WIZARD_COMPLETED_STEP_ID,
    UNKNOWN_VALUE,
    GITHUB_REST_API_URL,
    GITHUB_API_VERSION,
    GETH_SYSTEMD_SERVICE_NAME,
    MIN_CLIENT_VERSION_FOR_MERGE,
    LINUX_JWT_TOKEN_FILE_PATH,
    MAINTENANCE_DO_NOTHING,
    MAINTENANCE_RESTART_SERVICE,
    MAINTENANCE_UPGRADE_CLIENT,
    MAINTENANCE_UPGRADE_CLIENT_MERGE,
    MAINTENANCE_CONFIG_CLIENT_MERGE,
    MAINTENANCE_CHECK_AGAIN_SOON,
    MAINTENANCE_START_SERVICE,
    MAINTENANCE_REINSTALL_CLIENT,
    LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
    LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME,
    LIGHTHOUSE_LATEST_RELEASE,
    LIGHTHOUSE_INSTALLED_DIRECTORY,
    LIGHTHOUSE_INSTALLED_PATH,
    LIGHTHOUSE_PRIME_PGP_KEY_ID,
    BN_VERSION_EP,
    PGP_KEY_SERVERS,
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
    selected_network = CTX_SELECTED_NETWORK

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]
    current_network = context[selected_network]

    # Get execution client details

    execution_client_details = get_execution_client_details(current_execution_client)
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
    available_version = execution_client_details['versions']['available']
    if available_version != UNKNOWN_VALUE:
        available_version = parse_version(available_version)
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

    is_available_exec_merge_ready = False
    if is_version(available_version) and is_version(merge_ready_exec_version):
        if available_version >= merge_ready_exec_version:
            is_available_exec_merge_ready = True

    # If the available version is older than the latest one, we need to check again soon
    # It simply means that the updated build is not available yet for installing

    if is_version(latest_version) and is_version(available_version):
        if available_version < latest_version:
            execution_client_details['next_step'] = MAINTENANCE_CHECK_AGAIN_SOON

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

    if is_version(installed_version) and is_version(available_version):
        if installed_version < available_version:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT
        
        # If the next version is merge ready and we are not configured yet, we need to upgrade and
        # configure the client

        if is_available_exec_merge_ready and not execution_client_details['is_merge_configured']:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT_MERGE


    # If the service is not installed or found, we need to reinstall the client

    if not execution_client_details['service']['found']:
        execution_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # Get consensus client details

    consensus_client_details = get_consensus_client_details(current_consensus_client)
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
        MAINTENANCE_CHECK_AGAIN_SOON: 'Check again. Client update should be available soon.',
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
        f'A: {execution_client_details["versions"]["available"]}, '
        f'L: {execution_client_details["versions"]["latest"]})\n'
        f'Service is running: {execution_client_details["service"]["running"]}\n'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(execution_client_details["next_step"], UNKNOWN_VALUE)}')

    cc_section = (f'<b>Lighthouse</b> details (I: {consensus_client_details["versions"]["installed"]}, '
        f'R: {consensus_client_details["versions"]["running"]}, '
        f'L: {consensus_client_details["versions"]["latest"]})\n'
        f'Running services - Beacon node: {consensus_client_details["bn_service"]["running"]}, Validator client: {consensus_client_details["vc_service"]["running"]}\n'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(consensus_client_details["next_step"], UNKNOWN_VALUE)}')

    result = button_dialog(
        title='Maintenance Dashboard',
        text=(HTML(
f'''
Here are some details about your Ethereum clients.

{ec_section}

{cc_section}

{maintenance_message}

Versions legend - I: Installed, R: Running, A: Available, L: Latest
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
    # Return true if this systemd service is running
    return (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    )

def parse_exec_start(exec_start_struct):
    # Parse the ExecStart output of `systemctl show` to extract important details

    # Typical ExecStart value is like: { path=/usr/local/bin/lighthouse ; argv[]=/usr/local/bin/lighthouse bn --network prater --datadir /var/lib/lighthouse --http --execution-endpoint http://127.0.0.1:8551 --metrics --validator-monitor-auto --checkpoint-sync-url=https://goerli.checkpoint-sync.ethdevops.io --execution-jwt=/var/lib/ethereum/jwttoken --port 54949 --target-peers 100 --private ; ignore_errors=no ; start_time=[Wed 2022-08-03 12:57:32 UTC] ; stop_time=[n/a] ; pid=70252 ; code=(null) ; status=0/0 }

    path = UNKNOWN_VALUE
    argv = []

    result = re.match(r'\{\s*(.+)\s*\}', exec_start_struct)
    if not result:
        return {
            'path': path,
            'argv': argv
        }

    without_brackets = result.group(1)

    key_values = without_brackets.split(' ; ')

    for item in key_values:
        first_equal = item.find('=')
        if first_equal < 0:
            continue
        key = item[:first_equal].lower()
        value = item[first_equal + 1:]

        if key == 'path':
            path = value
        elif key == 'argv[]':
            argv = value.split(' ')

    return {
        'path': path,
        'argv': argv
    }

def get_execution_client_details(execution_client):
    # Get the details for the current execution client

    if execution_client == EXECUTION_CLIENT_GETH:

        details = {
            'service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE
            },
            'versions': {
                'installed': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE,
                'available': UNKNOWN_VALUE,
                'latest': UNKNOWN_VALUE
            },
            'exec': {
                'path': UNKNOWN_VALUE,
                'argv': []
            },
            'is_merge_configured': UNKNOWN_VALUE
        }
        
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
        details['service']['running'] = is_service_running(service_details)

        details['versions']['installed'] = get_geth_installed_version()
        details['versions']['running'] = get_geth_running_version(log)
        details['versions']['available'] = get_geth_available_version()
        details['versions']['latest'] = get_geth_latest_version(log)

        if 'ExecStart' in service_details:
            details['exec'] = parse_exec_start(service_details['ExecStart'])

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

def get_geth_available_version():
    # Get the available version for Geth, potentially for update

    log.info('Getting Geth available version...')

    # Add Ethereum PPA if not already added.
    if not is_ethereum_ppa_added():
        spc_package_installed = False
        try:
            spc_package_installed = is_package_installed('software-properties-common')
        except Exception:
            return False
        
        if not spc_package_installed:
            subprocess.run([
                'apt', '-y', 'update'])
            subprocess.run([
                'apt', '-y', 'install', 'software-properties-common'])

        subprocess.run(['add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
    else:
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

def get_consensus_client_details(consensus_client):
    # Get the details for the current consensus client

    if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        details = {
            'bn_service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE
            },
            'vc_service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE
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
        
        # Check for existing systemd services
        lighthouse_bn_service_exists = False
        lighthouse_bn_service_name = LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(lighthouse_bn_service_name)

        if service_details['LoadState'] == 'loaded':
            lighthouse_bn_service_exists = True

            details['bn_service']['found'] = True
            details['bn_service']['load'] = service_details['LoadState']
            details['bn_service']['active'] = service_details['ActiveState']
            details['bn_service']['sub'] = service_details['SubState']
            details['bn_service']['running'] = is_service_running(service_details)

        if 'ExecStart' in service_details:
            details['bn_exec'] = parse_exec_start(service_details['ExecStart'])

            execution_jwt_flag_found = False
            execution_endpoint_flag_found = False
            for arg in details['bn_exec']['argv']:
                if arg.lower().startswith('--execution-jwt'):
                    execution_jwt_flag_found = True
                if arg.lower().startswith('--execution-endpoint'):
                    execution_endpoint_flag_found = True
                if execution_jwt_flag_found and execution_endpoint_flag_found:
                    break
            
            details['is_bn_merge_configured'] = (
                execution_jwt_flag_found and execution_endpoint_flag_found)

        lighthouse_vc_service_exists = False
        lighthouse_vc_service_name = LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(lighthouse_vc_service_name)

        if service_details['LoadState'] == 'loaded':
            lighthouse_vc_service_exists = True
        
            details['vc_service']['found'] = True
            details['vc_service']['load'] = service_details['LoadState']
            details['vc_service']['active'] = service_details['ActiveState']
            details['vc_service']['sub'] = service_details['SubState']
            details['vc_service']['running'] = is_service_running(service_details)

        if 'ExecStart' in service_details:
            details['vc_exec'] = parse_exec_start(service_details['ExecStart'])

            for arg in details['vc_exec']['argv']:
                if arg.lower().startswith('--suggested-fee-recipient'):
                    details['is_vc_merge_configured'] = True
                    break
            
            if details['is_vc_merge_configured'] == UNKNOWN_VALUE:
                details['is_vc_merge_configured'] = False

        details['versions']['installed'] = get_lighthouse_installed_version()
        details['versions']['running'] = get_lighthouse_running_version()
        details['versions']['latest'] = get_lighthouse_latest_version()

        return details

    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

def get_lighthouse_installed_version():
    # Get the installed version for Lighthouse

    log.info('Getting Lighthouse installed version...')

    process_result = subprocess.run([LIGHTHOUSE_INSTALLED_PATH, '--version'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from Lighthouse. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Lighthouse v?(?P<version>[^-]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Lighthouse installed version.')
        return UNKNOWN_VALUE
    
    installed_version = result.group('version')

    log.info(f'Lighthouse installed version is {installed_version}')

    return installed_version

def get_lighthouse_running_version():
    # Get the running version for Lighthouse

    log.info('Getting Lighthouse running version...')

    local_lighthouse_bn_version_url = 'http://127.0.0.1:5052' + BN_VERSION_EP

    try:
        response = httpx.get(local_lighthouse_bn_version_url)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Lighthouse. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_lighthouse_bn_version_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'data' not in response_json or 'version' not in response_json['data']:
        log.error(f'Unexpected JSON response from {local_lighthouse_bn_version_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['data']['version']

    # Version agent should look like: Lighthouse/v2.0.1-aaa5344/x86_64-linux
    result = re.search(r'Lighthouse/v(?P<version>[^-/]+)(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Lighthouse version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Lighthouse running version is {running_version}')

    return running_version

def get_lighthouse_latest_version():
    # Get the latest version for Lighthouse

    log.info('Getting Lighthouse latest version...')

    lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(lighthouse_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Lighthouse. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Lighthouse. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Lighthouse.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Lighthouse version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Lighthouse latest version is {latest_version}')

    return latest_version

def perform_maintenance(execution_client, execution_client_details, consensus_client,
    consensus_client_details):
    # Perform all the maintenance tasks

    if execution_client == EXECUTION_CLIENT_GETH:
        # Geth maintenance tasks

        if execution_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Geth service...')

            subprocess.run(['systemctl', 'restart', GETH_SYSTEMD_SERVICE_NAME])

        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_geth():
                log.error('We could not upgrade the Geth client.')
                return False
        
        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            if not config_geth_merge():
                log.error('We could not configure Geth for the merge.')
                return False
            
            if not upgrade_geth():
                log.error('We could not upgrade the Geth client.')
                return False
    
        elif execution_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            if not config_geth_merge():
                log.error('We could not configure Geth for the merge.')
                return False
            
            log.info('Restarting Geth service...')

            subprocess.run(['systemctl', 'restart', GETH_SYSTEMD_SERVICE_NAME])

        elif execution_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Geth service...')

            subprocess.run(['systemctl', 'start', GETH_SYSTEMD_SERVICE_NAME])

        elif execution_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warn('TODO: Reinstalling client is to be implemented.')
    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False
    
    if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:
        # Lighthouse maintenance tasks

        if consensus_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Lighthouse services...')

            subprocess.run(['systemctl', 'restart', LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
                LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME])

        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_lighthouse():
                log.error('We could not upgrade the Lighthouse client.')
                return False
        
        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            if not config_lighthouse_merge():
                log.error('We could not configure Lighthouse for the merge.')
                return False

            if not upgrade_lighthouse():
                log.error('We could not upgrade the Lighthouse client.')
                return False
    
        elif consensus_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            if not config_lighthouse_merge():
                log.error('We could not configure Lighthouse for the merge.')
                return False
            
            log.info('Restarting Lighthouse services...')

            subprocess.run(['systemctl', 'restart', LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
                LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME])
            
        elif consensus_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Lighthouse services...')

            subprocess.run(['systemctl', 'start', LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
                LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME])

        elif consensus_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warn('TODO: Reinstalling client is to be implemented.')
    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

    return True

def upgrade_geth():
    # Upgrade the Geth client
    log.info('Upgrading Geth client...')

    # Add Ethereum PPA if not already added.
    if not is_ethereum_ppa_added():
        spc_package_installed = False
        try:
            spc_package_installed = is_package_installed('software-properties-common')
        except Exception:
            return False
        
        if not spc_package_installed:
            subprocess.run([
                'apt', '-y', 'update'])
            subprocess.run([
                'apt', '-y', 'install', 'software-properties-common'])

        subprocess.run(['add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
    else:
        subprocess.run(['apt', '-y', 'update'])

    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'

    subprocess.run(['apt', '-y', 'install', 'geth'], env=env)

    log.info('Restarting Geth service...')
    subprocess.run(['systemctl', 'restart', GETH_SYSTEMD_SERVICE_NAME])

    return True

def config_geth_merge():
    # Configure Geth for the merge
    log.info('Configuring Geth for the merge...')

    log.info('Creating JWT token file if needed...')
    if not setup_jwt_token_file():
        log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
        )

        return False
    
    geth_service_name = GETH_SYSTEMD_SERVICE_NAME
    geth_service_content = ''

    log.info('Adding JWT token configuration to Geth...')

    with open('/etc/systemd/system/' + geth_service_name, 'r') as service_file:
        geth_service_content = service_file.read()

    result = re.search(r'ExecStart\s*=\s*(.*?)geth([^\\\n]*(\\\s+)?)*', geth_service_content)
    if not result:
        log.error('Cannot parse Geth service file.')
        return False
    
    exec_start = result.group(0)

    # Add --authrpc.jwtsecret configuration
    exec_start = re.sub(r'(\s*\\)?\s+--authrpc.jwtsecret\s*=?\s*\S+', '', exec_start)
    exec_start = exec_start + f' --authrpc.jwtsecret {LINUX_JWT_TOKEN_FILE_PATH}'

    geth_service_content = re.sub(r'ExecStart\s*=\s*(.*?)geth([^\\\n]*(\\\s+)?)*',
        exec_start, geth_service_content)

    # Write back configuration
    with open('/etc/systemd/system/' + geth_service_name, 'w') as service_file:
        service_file.write(geth_service_content)

    # Reload configuration
    log.info('Reloading service configurations...')
    subprocess.run(['systemctl', 'daemon-reload'])

    return True

def upgrade_lighthouse():
    # Upgrade the Lighthouse client
    log.info('Upgrading Lighthouse client...')

    # Getting latest Lighthouse release files
    lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(lighthouse_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading lighthouse binary. {exception}')
        return False

    if response.status_code != 200:
        log.error(f'HTTP error while downloading lighthouse binary. '
            f'Status code {response.status_code}')
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        log.error('No assets in Github release for lighthouse.')
        return False
    
    binary_asset = None
    signature_asset = None

    archive_filename_comp = 'x86_64-unknown-linux-gnu.tar.gz'

    use_optimized_binary = is_adx_supported()
    if not use_optimized_binary:
        log.warn('CPU does not support ADX instructions. '
            'Using the portable version for Lighthouse.')
        archive_filename_comp = 'x86_64-unknown-linux-gnu-portable.tar.gz'
    
    archive_filename_sig_comp = archive_filename_comp + '.asc'

    for asset in release_json['assets']:
        if 'name' not in asset:
            continue
        if 'browser_download_url' not in asset:
            continue

        file_name = asset['name']
        file_url = asset['browser_download_url']

        if file_name.endswith(archive_filename_comp):
            binary_asset = {
                'file_name': file_name,
                'file_url': file_url
            }
        elif file_name.endswith(archive_filename_sig_comp):
            signature_asset = {
                'file_name': file_name,
                'file_url': file_url
            }

    if binary_asset is None or signature_asset is None:
        log.error('Could not find binary or signature asset in Github release.')
        return False
    
    # Downloading latest Lighthouse release files
    download_path = Path(Path.home(), 'ethwizard', 'downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    binary_path = Path(download_path, binary_asset['file_name'])

    try:
        with open(binary_path, 'wb') as binary_file:
            with httpx.stream('GET', binary_asset['file_url'],
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'HTTP error while downloading Lighthouse binary from Github. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading Lighthouse binary from Github. {exception}')
        return False
    
    signature_path = Path(download_path, signature_asset['file_name'])

    try:
        with open(signature_path, 'wb') as signature_file:
            with httpx.stream('GET', signature_asset['file_url'],
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'HTTP error while downloading Lighthouse signature from Github. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    signature_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading Lighthouse signature from Github. {exception}')
        return False

    # Test if gpg is already installed
    gpg_is_installed = False
    try:
        gpg_is_installed = is_package_installed('gpg')
    except Exception:
        return False

    if not gpg_is_installed:
        # Install gpg using APT
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'gpg'])

    # Verify PGP signature

    command_line = ['gpg', '--list-keys', '--with-colons', LIGHTHOUSE_PRIME_PGP_KEY_ID]
    process_result = subprocess.run(command_line)
    pgp_key_found = process_result.returncode == 0

    if not pgp_key_found:
        retry_index = 0
        retry_count = 15

        key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
        log.info(f'Downloading Sigma Prime\'s PGP key from {key_server} ...')
        command_line = ['gpg', '--keyserver', key_server, '--recv-keys',
            LIGHTHOUSE_PRIME_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                delay = 5
                log.warning(f'GPG failed to download the PGP key. We will wait {delay} seconds '
                    f'and try again from a different server.')
                time.sleep(delay)

                key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
                log.info(f'Downloading Sigma Prime\'s PGP key from {key_server} ...')
                command_line = ['gpg', '--keyserver', key_server, '--recv-keys',
                    LIGHTHOUSE_PRIME_PGP_KEY_ID]

                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            log.error(
f'''
We failed to download the Sigma Prime's PGP key to verify the lighthouse
binary after {retry_count} retries.
'''
            )
            return False
    
    process_result = subprocess.run([
        'gpg', '--verify', signature_path])
    if process_result.returncode != 0:
        log.error('The lighthouse binary signature is wrong. '
            'We will stop here to protect you.')
        return False
    
    # Stopping Lighthouse services before updating the binary
    log.info('Stopping Lighthouse services...')
    subprocess.run(['systemctl', 'stop', LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
        LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME])

    # Extracting the Lighthouse binary archive
    log.info('Updating Lighthouse binary...')
    subprocess.run([
        'tar', 'xvf', binary_path, '--directory', LIGHTHOUSE_INSTALLED_DIRECTORY])
    
    # Restarting Lighthouse services after updating the binary
    log.info('Starting Lighthouse services...')
    subprocess.run(['systemctl', 'start', LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
        LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME])

    # Remove download leftovers
    binary_path.unlink()
    signature_path.unlink()

    return True

def config_lighthouse_merge():
    # Configure Lighthouse for the merge
    log.info('Configuring Lighthouse for the merge...')

    fee_recipient_address = select_fee_recipient_address()
    if not fee_recipient_address:
        log.error('No fee recipient address entered.')
        return False

    log.info('Creating JWT token file if needed...')
    if not setup_jwt_token_file():
        log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
        )

        return False
    
    # Configure the Lighthouse beacon node

    lighthouse_bn_service_name = LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME
    lighthouse_bn_service_content = ''

    log.info('Adding JWT token configuration to Lighthouse beacon node and '
        'using the correct API port...')

    with open('/etc/systemd/system/' + lighthouse_bn_service_name, 'r') as service_file:
        lighthouse_bn_service_content = service_file.read()

    result = re.search(r'ExecStart\s*=\s*(.*?)lighthouse([^\\\n]*(\\\s+)?)*', lighthouse_bn_service_content)
    if not result:
        log.error('Cannot parse Lighthouse beacon node service file.')
        return False
    
    exec_start = result.group(0)

    # Remove all --eth1-endpoints related configuration
    exec_start = re.sub(r'(\s*\\)?\s+--eth1-endpoints?\s*=?\s*\S+', '', exec_start)

    # Add --execution-endpoint configuration
    exec_start = re.sub(r'(\s*\\)?\s+--execution-endpoints?\s*=?\s*\S+', '', exec_start)
    exec_start = exec_start + ' --execution-endpoint http://127.0.0.1:8551'

    # Add --execution-jwt configuration
    exec_start = re.sub(r'(\s*\\)?\s+--execution-jwt\s*=?\s*\S+', '', exec_start)
    exec_start = exec_start + f' --execution-jwt {LINUX_JWT_TOKEN_FILE_PATH}'

    lighthouse_bn_service_content = re.sub(r'ExecStart\s*=\s*(.*?)lighthouse([^\\\n]*(\\\s+)?)*',
        exec_start, lighthouse_bn_service_content)

    # Write back configuration
    with open('/etc/systemd/system/' + lighthouse_bn_service_name, 'w') as service_file:
        service_file.write(lighthouse_bn_service_content)

    # Configure the Lighthouse validator client

    lighthouse_vc_service_name = LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME
    lighthouse_vc_service_content = ''

    with open('/etc/systemd/system/' + lighthouse_vc_service_name, 'r') as service_file:
        lighthouse_vc_service_content = service_file.read()
    
    result = re.search(r'ExecStart\s*=\s*(.*?)lighthouse([^\\\n]*(\\\s+)?)*', lighthouse_vc_service_content)
    if not result:
        log.error('Cannot parse Lighthouse validator client service file.')
        return False

    exec_start = result.group(0)

    # Add fee recipient address
    exec_start = re.sub(r'(\s*\\)?\s+--suggested-fee-recipient\s*=?\s*\S+', '', exec_start)
    exec_start = exec_start + f' --suggested-fee-recipient {fee_recipient_address}'
    
    lighthouse_vc_service_content = re.sub(r'ExecStart\s*=\s*(.*?)lighthouse([^\\\n]*(\\\s+)?)*',
        exec_start, lighthouse_vc_service_content)

    # Write back configuration
    with open('/etc/systemd/system/' + lighthouse_vc_service_name, 'w') as service_file:
        service_file.write(lighthouse_vc_service_content)

    # Reload configuration
    log.info('Reloading service configurations...')
    subprocess.run(['systemctl', 'daemon-reload'])

    return True

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