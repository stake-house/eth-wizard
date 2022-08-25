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
    WINDOWS_SERVICE_RUNNING
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

    return False

    # Get consensus client details

    """consensus_client_details = get_consensus_client_details(current_consensus_client)
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
            return False"""

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