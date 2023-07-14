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
    get_geth_latest_version,
    get_nethermind_running_version,
    get_nethermind_latest_version,
    get_mevboost_latest_version,
    get_nimbus_latest_version,
    get_lighthouse_latest_version
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
    setup_jwt_token_file,
    is_adx_supported
)

from ethwizard.constants import (
    CTX_SELECTED_EXECUTION_CLIENT,
    CTX_SELECTED_CONSENSUS_CLIENT,
    CTX_SELECTED_NETWORK,
    CTX_MEVBOOST_INSTALLED,
    CTX_SELECTED_DIRECTORY,
    EXECUTION_CLIENT_GETH,
    EXECUTION_CLIENT_NETHERMIND,
    CONSENSUS_CLIENT_TEKU,
    CONSENSUS_CLIENT_NIMBUS,
    CONSENSUS_CLIENT_LIGHTHOUSE,
    WIZARD_COMPLETED_STEP_ID,
    UNKNOWN_VALUE,
    MAINTENANCE_DO_NOTHING,
    MIN_CLIENT_VERSION_FOR_MERGE,
    MAINTENANCE_START_SERVICE,
    MAINTENANCE_RESTART_SERVICE,
    MAINTENANCE_CONFIG_CLIENT_MERGE,
    MAINTENANCE_CHECK_AGAIN_SOON,
    MAINTENANCE_UPGRADE_CLIENT,
    MAINTENANCE_UPGRADE_CLIENT_MERGE,
    MAINTENANCE_REINSTALL_CLIENT,
    MAINTENANCE_IMPROVE_TIMEOUT,
    WINDOWS_SERVICE_RUNNING,
    BN_VERSION_EP,
    GITHUB_REST_API_URL,
    GITHUB_API_VERSION,
    MEVBOOST_LATEST_RELEASE,
    TEKU_LATEST_RELEASE,
    NIMBUS_LATEST_RELEASE,
    LIGHTHOUSE_LATEST_RELEASE,
    LIGHTHOUSE_PRIME_PGP_KEY_ID,
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
    mevboost_installed = CTX_MEVBOOST_INSTALLED

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]
    current_network = context[selected_network]
    current_directory = context[selected_directory]
    current_execution_improved_service_timeout = context[execution_improved_service_timeout]
    current_consensus_improved_service_timeout = context[consensus_improved_service_timeout]
    current_mevboost_installed = context[mevboost_installed]

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
    available_version = execution_client_details['versions'].get('available', UNKNOWN_VALUE)
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

    is_latest_exec_merge_ready = False
    if is_version(latest_version) and is_version(merge_ready_exec_version):
        if latest_version >= merge_ready_exec_version:
            is_latest_exec_merge_ready = True

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

    target_version = latest_version
    if is_version(available_version):
        target_version = available_version

    if is_version(installed_version) and is_version(target_version):
        if installed_version < target_version:
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

    if consensus_client_details['single_service']:

        if not consensus_client_details['service']['running']:
            consensus_client_details['next_step'] = MAINTENANCE_START_SERVICE

    else:

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

    if consensus_client_details['single_service']:

        if is_version(installed_version):
            if is_installed_cons_merge_ready and (
                not consensus_client_details['is_merge_configured']):
                consensus_client_details['next_step'] = MAINTENANCE_CONFIG_CLIENT_MERGE

    else:

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

            if consensus_client_details['single_service']:

                if is_latest_cons_merge_ready and (
                    not consensus_client_details['is_merge_configured']):
                    consensus_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT_MERGE

            else:

                if is_latest_cons_merge_ready and (
                    not consensus_client_details['is_bn_merge_configured'] or
                    not consensus_client_details['is_vc_merge_configured']):
                    consensus_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT_MERGE

    # If the service is not installed or found, we need to reinstall the client

    if consensus_client_details['single_service']:

        if not consensus_client_details['service']['found']:
            consensus_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    else:

        if (not consensus_client_details['bn_service']['found'] or
            not consensus_client_details['vc_service']['found']):
            consensus_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # Get MEV-Boost details

    mevboost_details = None

    if current_mevboost_installed:

        mevboost_details = get_mevboost_details(current_directory)
        if not mevboost_details:
            log.error('Unable to get MEV-Boost details.')
            return False

        # Find out if we need to do maintenance for MEV-Boost

        mevboost_details['next_step'] = MAINTENANCE_DO_NOTHING

        installed_version = mevboost_details['versions']['installed']
        if installed_version != UNKNOWN_VALUE:
            installed_version = parse_version(installed_version)
        latest_version = mevboost_details['versions']['latest']
        if latest_version != UNKNOWN_VALUE:
            latest_version = parse_version(latest_version)
        
        # If the service is not running, we need to start it

        if not mevboost_details['service']['running']:
            mevboost_details['next_step'] = MAINTENANCE_START_SERVICE

        # If the installed version is older than the available one, we need to upgrade the client

        if is_version(installed_version) and is_version(latest_version):
            if installed_version < latest_version:
                mevboost_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT

        # If the service is not installed or found, we need to reinstall the client

        if not mevboost_details['service']['found']:
            mevboost_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # We only need to do maintenance if one of clients or MEV-Boost needs maintenance.

    no_maintenance_tasks = set((MAINTENANCE_DO_NOTHING, MAINTENANCE_CHECK_AGAIN_SOON))

    maintenance_needed = (
        execution_client_details['next_step'] not in no_maintenance_tasks or
        consensus_client_details['next_step'] not in no_maintenance_tasks or
        (mevboost_details is not None and mevboost_details['next_step'] not in no_maintenance_tasks)
        )

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

    ec_available_version_section = ''

    if execution_client_details['versions'].get('available', UNKNOWN_VALUE) != UNKNOWN_VALUE:
        ec_available_version_section = f'A: {execution_client_details["versions"]["available"]}, '

    ec_section = (f'<b>{current_execution_client}</b> details (I: {execution_client_details["versions"]["installed"]}, '
        f'R: {execution_client_details["versions"]["running"]}, '
        f'{ec_available_version_section}'
        f'L: {execution_client_details["versions"]["latest"]})\n'
        f'Service is running: {execution_client_details["service"]["running"]}\n'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(execution_client_details["next_step"], UNKNOWN_VALUE)}')

    cc_running_service_section = ''

    if consensus_client_details['single_service']:

        cc_running_service_section = f'Service is running: {consensus_client_details["service"]["running"]}\n'

    else:

        cc_running_service_section = (
            f'Running services - Beacon node: {consensus_client_details["bn_service"]["running"]}'
            f', Validator client: {consensus_client_details["vc_service"]["running"]}\n'
        )

    cc_section = (f'<b>{current_consensus_client}</b> details (I: {consensus_client_details["versions"]["installed"]}, '
        f'R: {consensus_client_details["versions"]["running"]}, '
        f'L: {consensus_client_details["versions"]["latest"]})\n'
        f'{cc_running_service_section}'
        f'<b>Maintenance task</b>: {maintenance_tasks_description.get(consensus_client_details["next_step"], UNKNOWN_VALUE)}')

    mb_section = ''

    if current_mevboost_installed:
        mb_section = (f'\n\n<b>MEV-Boost</b> details (I: {mevboost_details["versions"]["installed"]}, '
            f'L: {mevboost_details["versions"]["latest"]})\n'
            f'Service is running: {mevboost_details["service"]["running"]}\n'
            f'<b>Maintenance task</b>: {maintenance_tasks_description.get(mevboost_details["next_step"], UNKNOWN_VALUE)}')

    result = button_dialog(
        title='Maintenance Dashboard',
        text=(HTML(
f'''
Here are some details about your Ethereum clients.

{ec_section}

{cc_section}{mb_section}

{maintenance_message}

Versions legend - I: Installed, R: Running, L: Latest
'''             )),
        buttons=buttons
    ).run()

    if not result:
        return False
    
    if result == 1:
        maintenance_result = perform_maintenance(current_directory, current_execution_client,
            execution_client_details, current_consensus_client, consensus_client_details,
            mevboost_details, context)
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

def get_mevboost_details(base_directory):
    # Get the details for MEV-Boost

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

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
            'latest': UNKNOWN_VALUE
        },
        'exec': {
            'path': UNKNOWN_VALUE,
            'argv': []
        },
    }
    
    # Check for existing service
    mevboost_service_exists = False
    mevboost_service_name = 'mevboost'

    service_details = get_service_details(nssm_binary, mevboost_service_name)

    if service_details is not None:
        mevboost_service_exists = True
    
    if not mevboost_service_exists:
        return details

    details['service']['found'] = True
    details['service']['status'] = service_details['status']
    details['service']['binary'] = service_details['install']
    details['service']['parameters'] = service_details['parameters']['AppParameters']
    details['service']['running'] = is_service_running(service_details)

    details['versions']['installed'] = get_mevboost_installed_version(base_directory)
    details['versions']['latest'] = get_mevboost_latest_version(log)

    details['exec']['path'] = service_details['install']
    details['exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

    return details

def get_mevboost_installed_version(base_directory):
    # Get the installed version for MEV-Boost

    log.info('Getting MEV-Boost installed version...')

    mevboost_path = base_directory.joinpath('bin', 'mev-boost.exe')

    process_result = subprocess.run([mevboost_path, '--version'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from MEV-Boost. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'mev-boost v?(?P<version>\S+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for MEV-Boost installed version.')
        return UNKNOWN_VALUE
    
    installed_version = result.group('version')

    log.info(f'MEV-Boost installed version is {installed_version}')

    return installed_version

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

    elif execution_client == EXECUTION_CLIENT_NETHERMIND:

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
                'latest': UNKNOWN_VALUE,
                'available': UNKNOWN_VALUE
            },
            'exec': {
                'path': UNKNOWN_VALUE,
                'argv': []
            },
            'is_merge_configured': UNKNOWN_VALUE
        }

        # Check for existing service
        nethermind_service_exists = False
        nethermind_service_name = 'nethermind'

        service_details = get_service_details(nssm_binary, nethermind_service_name)

        if service_details is not None:
            nethermind_service_exists = True
        
        if not nethermind_service_exists:
            return details

        details['service']['found'] = True
        details['service']['status'] = service_details['status']
        details['service']['binary'] = service_details['install']
        details['service']['parameters'] = service_details['parameters']['AppParameters']
        details['service']['running'] = is_service_running(service_details)

        details['versions']['installed'] = get_nethermind_installed_version(base_directory)
        details['versions']['running'] = get_nethermind_running_version(log)
        details['versions']['available'] = get_nethermind_available_version()
        details['versions']['latest'] = get_nethermind_latest_version(log)

        details['exec']['path'] = service_details['install']
        details['exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        for arg in details['exec']['argv']:
            if arg.lower().startswith('--JsonRpc.JwtSecretFile'.lower()):
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

def get_nethermind_installed_version(base_directory):
    # Get the installed version for Nethermind

    log.info('Getting Nethermind installed version...')

    nethermind_dir = base_directory.joinpath('bin', 'Nethermind')
    nethermind_path = nethermind_dir.joinpath('Nethermind.Runner.exe')

    nethermind_version = UNKNOWN_VALUE

    if nethermind_path.is_file():
        try:
            process_result = subprocess.run([
                str(nethermind_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            
            if process_result.returncode != 0:
                log.error(f'Unexpected return code from Nethermind. Return code: '
                    f'{process_result.returncode}')
                return UNKNOWN_VALUE

            process_output = process_result.stdout
            result = re.search(r'Version: (?P<version>[^-\+]+)', process_output)
            if not result:
                log.error(f'Cannot parse {process_output} for Geth installed version.')
                return UNKNOWN_VALUE
            
            nethermind_version = result.group('version').strip()

        except FileNotFoundError:
            log.error(f'Cannot find Nethermind in {nethermind_path} for installed version.')
            return UNKNOWN_VALUE
    
    installed_version = nethermind_version

    log.info(f'Nethermind installed version is {installed_version}')

    return installed_version

def get_nethermind_available_version():
    # Get the available version for Nethermind

    command = ['winget', 'show', 'nethermind', '--disable-interactivity', '--accept-source-agreements']

    process_result = subprocess.run(command, capture_output=True, text=True)
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from winget and getting the latest available Nethermind '
            f'version. Return code: {process_result.returncode}')
        return UNKNOWN_VALUE
    
    nethermind_version = UNKNOWN_VALUE

    process_output = process_result.stdout
    result = re.search(r'\nVersion: (?P<version>[^-\+\n]+)', process_output)
    if result:
        nethermind_version = result.group('version').strip()

    available_version = nethermind_version

    log.info(f'Nethermind available version is {available_version}')

    return available_version

def get_consensus_client_details(base_directory, consensus_client):
    # Get the details for the current consensus client

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    if consensus_client == CONSENSUS_CLIENT_TEKU:

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
            'is_merge_configured': UNKNOWN_VALUE,
            'single_service': True,
        }
        
        # Check for existing service
        teku_service_exists = False
        teku_service_name = 'teku'

        service_details = get_service_details(nssm_binary, teku_service_name)

        if service_details is not None:
            teku_service_exists = True
        
        if not teku_service_exists:
            return details

        details['service']['found'] = True
        details['service']['status'] = service_details['status']
        details['service']['binary'] = service_details['install']
        details['service']['parameters'] = service_details['parameters']['AppParameters']
        details['service']['running'] = is_service_running(service_details)

        details['exec']['path'] = service_details['install']
        details['exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        execution_jwt_flag_found = False
        execution_endpoint_flag_found = False
        for arg in details['exec']['argv']:
            if arg.lower().startswith('--ee-jwt-secret-file'):
                execution_jwt_flag_found = True
            if arg.lower().startswith('--ee-endpoint'):
                execution_endpoint_flag_found = True
            if execution_jwt_flag_found and execution_endpoint_flag_found:
                break
        
        details['is_merge_configured'] = (
            execution_jwt_flag_found and execution_endpoint_flag_found)

        details['versions']['installed'] = get_teku_installed_version(base_directory)
        details['versions']['running'] = get_teku_running_version()
        details['versions']['latest'] = get_teku_latest_version()

        return details

    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

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
            'is_merge_configured': UNKNOWN_VALUE,
            'single_service': True,
        }
        
        # Check for existing service
        nimbus_service_exists = False
        nimbus_service_name = 'nimbus'

        service_details = get_service_details(nssm_binary, nimbus_service_name)

        if service_details is not None:
            nimbus_service_exists = True
        
        if not nimbus_service_exists:
            return details

        details['service']['found'] = True
        details['service']['status'] = service_details['status']
        details['service']['binary'] = service_details['install']
        details['service']['parameters'] = service_details['parameters']['AppParameters']
        details['service']['running'] = is_service_running(service_details)

        details['exec']['path'] = service_details['install']
        details['exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        execution_jwt_flag_found = False
        for arg in details['exec']['argv']:
            if arg.lower().startswith('--jwt-secret'):
                execution_jwt_flag_found = True
                break
        
        details['is_merge_configured'] = execution_jwt_flag_found

        details['versions']['installed'] = get_nimbus_installed_version(base_directory)
        details['versions']['running'] = get_nimbus_running_version()
        details['versions']['latest'] = get_nimbus_latest_version(log)

        return details

    elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        details = {
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
            'is_vc_merge_configured': UNKNOWN_VALUE,
            'single_service': False,
        }
        
        # Check for existing services
        lighthouse_bn_service_exists = False
        lighthouse_bn_service_name = 'lighthousebeacon'

        service_details = get_service_details(nssm_binary, lighthouse_bn_service_name)

        if service_details is not None:
            lighthouse_bn_service_exists = True
        
        if not lighthouse_bn_service_exists:
            return details

        details['bn_service']['found'] = True
        details['bn_service']['status'] = service_details['status']
        details['bn_service']['binary'] = service_details['install']
        details['bn_service']['parameters'] = service_details['parameters']['AppParameters']
        details['bn_service']['running'] = is_service_running(service_details)

        details['bn_exec']['path'] = service_details['install']
        details['bn_exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

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
        lighthouse_vc_service_name = 'lighthousevalidator'

        service_details = get_service_details(nssm_binary, lighthouse_vc_service_name)

        if service_details is not None:
            lighthouse_vc_service_exists = True
        
        if not lighthouse_vc_service_exists:
            return details

        details['vc_service']['found'] = True
        details['vc_service']['status'] = service_details['status']
        details['vc_service']['binary'] = service_details['install']
        details['vc_service']['parameters'] = service_details['parameters']['AppParameters']
        details['vc_service']['running'] = is_service_running(service_details)

        details['vc_exec']['path'] = service_details['install']
        details['vc_exec']['argv'] = shlex.split(service_details['parameters']['AppParameters'], posix=False)

        for arg in details['vc_exec']['argv']:
            if arg.lower().startswith('--suggested-fee-recipient'):
                details['is_vc_merge_configured'] = True
                break

        details['versions']['installed'] = get_lighthouse_installed_version(base_directory)
        details['versions']['running'] = get_lighthouse_running_version()
        details['versions']['latest'] = get_lighthouse_latest_version(log)

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
            result = re.search(r'teku/v?(?P<version>[^/]+)', process_output)
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

def get_nimbus_running_version():
    # Get the running version for Nimbus

    log.info('Getting Nimbus running version...')

    local_nimbus_bn_version_url = 'http://127.0.0.1:5052' + BN_VERSION_EP

    try:
        response = httpx.get(local_nimbus_bn_version_url)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Nimbus. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_nimbus_bn_version_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'data' not in response_json or 'version' not in response_json['data']:
        log.error(f'Unexpected JSON response from {local_nimbus_bn_version_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['data']['version']

    # Version agent should look like: Nimbus/v23.5.1-4842c9-stateofus
    result = re.search(r'Nimbus/v?(?P<version>[^-/]+)(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Nimbus version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Nimbus running version is {running_version}')

    return running_version

def get_nimbus_installed_version(base_directory):
    # Get the installed version for Nimbus

    log.info('Getting Nimbus installed version...')

    nimbus_path = base_directory.joinpath('bin', 'nimbus_beacon_node.exe')

    nimbus_found = False
    nimbus_version = UNKNOWN_VALUE

    if nimbus_path.is_file():
        try:
            process_result = subprocess.run([
                str(nimbus_path), '--version'
                ], capture_output=True, text=True)
            
            if process_result.returncode != 0:
                log.error(f'Unexpected return code from Nimbus. Return code: '
                    f'{process_result.returncode}')
                return UNKNOWN_VALUE

            nimbus_found = True

            process_output = process_result.stdout
            result = re.search(r'Nimbus beacon node v?(?P<version>[^-]+)', process_output)
            if result:
                nimbus_version = result.group('version').strip()
            else:
                log.error(f'We could not parse Nimbus version from output: {process_result.stdout}')

        except FileNotFoundError:
            pass

    if nimbus_found:
        log.info(f'Nimbus installed version is {nimbus_version}')

        return nimbus_version
    
    return UNKNOWN_VALUE

def get_lighthouse_running_version():
    # Get the running version for Lighthouse

    log.info('Getting Lighthouse running version...')

    local_lighthouse_bn_version_url = 'http://127.0.0.1:5052' + BN_VERSION_EP

    try:
        response = httpx.get(local_lighthouse_bn_version_url)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Nimbus. Exception: {exception}')
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
    result = re.search(r'Lighthouse/v?(?P<version>[^-/]+)(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Lighthouse version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Lighthouse running version is {running_version}')

    return running_version

def get_lighthouse_installed_version(base_directory):
    # Get the installed version for Lighthouse

    log.info('Getting Lighthouse installed version...')

    lighthouse_path = base_directory.joinpath('bin', 'lighthouse.exe')

    lighthouse_found = False
    lighthouse_version = 'unknown'

    if lighthouse_path.is_file():
        try:
            process_result = subprocess.run([str(lighthouse_path), '--version'],
                capture_output=True, text=True)
            lighthouse_found = True

            if process_result.returncode != 0:
                log.error(f'Unexpected return code from Lighthouse. Return code: '
                    f'{process_result.returncode}')
                return UNKNOWN_VALUE

            process_output = process_result.stdout
            result = re.search(r'Lighthouse v?(?P<version>[^-]+)', process_output)
            if result:
                lighthouse_version = result.group('version').strip()
            else:
                log.error(f'We could not parse Lighthouse version from output: {process_result.stdout}')

        except FileNotFoundError:
            pass

    if lighthouse_found:
        log.info(f'Lighthouse installed version is {lighthouse_version}')

        return lighthouse_version
    
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
    mevboost_installed = CTX_MEVBOOST_INSTALLED

    updated_context = False

    if selected_execution_client not in context:
        context[selected_execution_client] = EXECUTION_CLIENT_GETH
        updated_context = True
    
    if selected_consensus_client not in context:
        context[selected_consensus_client] = CONSENSUS_CLIENT_TEKU
        updated_context = True
    
    if mevboost_installed not in context:
        context[mevboost_installed] = False
        updated_context = True
    
    if selected_network in context and context[selected_consensus_client] == 'prater':
        context[selected_consensus_client] = NETWORK_GOERLI
        updated_context = True
    
    if (execution_improved_service_timeout not in context and
        context[selected_execution_client] == EXECUTION_CLIENT_GETH):
        context[execution_improved_service_timeout] = False
        updated_context = True
    
    if (consensus_improved_service_timeout not in context and 
        context[selected_consensus_client] == CONSENSUS_CLIENT_TEKU):
        context[consensus_improved_service_timeout] = False
        updated_context = True

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return None

    return context

def perform_maintenance(base_directory, execution_client, execution_client_details,
    consensus_client, consensus_client_details, mevboost_details, context):
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

    elif execution_client == EXECUTION_CLIENT_NETHERMIND:
        # Nethermind maintenance tasks
        nethermind_service_name = 'nethermind'

        if execution_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Nethermind service...')

            subprocess.run([str(nssm_binary), 'restart', nethermind_service_name])

        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_nethermind(base_directory, nssm_binary):
                log.error('We could not upgrade the Nethermind client.')
                return False
        
        elif execution_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            log.warning('Upgrading Nethermind client for merge is not implemented. This should '
                'not be needed as Nethermind support was added after the merge.')
            return False
    
        elif execution_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            log.warning('Configuring Nethermind client for merge is not implemented. This should '
                'not be needed as Nethermind support was added after the merge.')
            return False

        elif execution_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Nethermind service...')

            subprocess.run([str(nssm_binary), 'start', nethermind_service_name])

        elif execution_client_details['next_step'] == MAINTENANCE_IMPROVE_TIMEOUT:
            log.warning('Impriving Nethermind service timeout is not implemented. This should '
                'not be needed as Nethermind support was added with proper timeout configuration.')
            return False

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
    
    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:
        # Nimbus maintenance tasks
        nimbus_service_name = 'nimbus'

        if consensus_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Nimbus service...')

            subprocess.run([str(nssm_binary), 'restart', nimbus_service_name])

        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_nimbus(base_directory, nssm_binary):
                log.error('We could not upgrade the Nimbus client.')
                return False
        
        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            log.warning('Upgrading Nimbus client for merge is not implemented. This should '
                'not be needed as Nimbus support was added after the merge.')
            return False
    
        elif consensus_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            log.warning('Configuring Nimbus client for merge is not implemented. This should '
                'not be needed as Nimbus support was added after the merge.')
            return False
            
        elif consensus_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Nimbus service...')

            subprocess.run([str(nssm_binary), 'start', nimbus_service_name])

        elif consensus_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warning('TODO: Reinstalling client is to be implemented.')
    
    elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:
        # Lighthouse maintenance tasks
        lighthouse_bn_service_name = 'lighthousebeacon'
        lighthouse_vc_service_name = 'lighthousevalidator'

        if consensus_client_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting Lighthouse services...')

            subprocess.run([str(nssm_binary), 'restart', lighthouse_bn_service_name])
            subprocess.run([str(nssm_binary), 'restart', lighthouse_vc_service_name])

        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_lighthouse(base_directory, nssm_binary):
                log.error('We could not upgrade the Lighthouse client.')
                return False
        
        elif consensus_client_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT_MERGE:
            log.warning('Upgrading Lighthouse client for merge is not implemented. This should '
                'not be needed as Lighthouse support was added after the merge.')
            return False
    
        elif consensus_client_details['next_step'] == MAINTENANCE_CONFIG_CLIENT_MERGE:
            log.warning('Configuring Lighthouse client for merge is not implemented. This should '
                'not be needed as Lighthouse support was added after the merge.')
            return False
            
        elif consensus_client_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting Lighthouse services...')

            subprocess.run([str(nssm_binary), 'start', lighthouse_bn_service_name])
            subprocess.run([str(nssm_binary), 'start', lighthouse_vc_service_name])

        elif consensus_client_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warning('TODO: Reinstalling client is to be implemented.')

    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

    if mevboost_details is not None:

        mevboost_service_name = 'mevboost'

        if mevboost_details['next_step'] == MAINTENANCE_RESTART_SERVICE:
            log.info('Restarting MEV-Boost service...')

            subprocess.run([str(nssm_binary), 'restart', mevboost_service_name])

        elif mevboost_details['next_step'] == MAINTENANCE_UPGRADE_CLIENT:
            if not upgrade_mevboost(base_directory, nssm_binary):
                log.error('We could not upgrade MEV-Boost.')
                return False

        elif mevboost_details['next_step'] == MAINTENANCE_START_SERVICE:
            log.info('Starting MEV-Boost service...')

            subprocess.run([str(nssm_binary), 'start', mevboost_service_name])

        elif mevboost_details['next_step'] == MAINTENANCE_REINSTALL_CLIENT:
            log.warning('TODO: Reinstalling MEV-Boost is to be implemented.')

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return False

    return context

def upgrade_mevboost(base_directory, nssm_binary):
    # Upgrade MEV-Boost
    log.info('Upgrading MEV-Boost...')

    # Getting latest mev-boost release files
    mevboost_gh_release_url = GITHUB_REST_API_URL + MEVBOOST_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(mevboost_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading MEV-Boost binary. {exception}')
        return False

    if response.status_code != 200:
        log.error(f'HTTP error while downloading MEV-Boost binary. '
            f'Status code {response.status_code}')
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        log.error('No assets in Github release for MEV-Boost.')
        return False
    
    binary_asset = None
    checksums_asset = None

    archive_filename_comp = 'windows_amd64.tar.gz'
    checksums_filename = 'checksums.txt'

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
        elif file_name == checksums_filename:
            checksums_asset = {
                'file_name': file_name,
                'file_url': file_url
            }

    if binary_asset is None or checksums_asset is None:
        log.error('Could not find binary or checksums asset in Github release.')
        return False
    else:
        archive_filename = binary_asset['file_name']
        log.info(f'Found {archive_filename} asset in Github release.')
    
    # Downloading latest MEV-Boost release files
    download_path = base_directory.joinpath('downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    binary_path = download_path.joinpath(binary_asset['file_name'])
    if binary_path.is_file():
        binary_path.unlink()

    binary_hash = hashlib.sha256()

    try:
        with open(binary_path, 'wb') as binary_file:
            with httpx.stream('GET', binary_asset['file_url'],
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'HTTP error while downloading MEV-Boost binary from Github. '
                        f'Status code {http_stream.status_code}')
                    return False

                archive_filename = binary_asset['file_name']
                archive_url = binary_asset['file_url']
                log.info(f'Downloading {archive_filename} from {archive_url} ...')

                for data in http_stream.iter_bytes():
                    binary_file.write(data)
                    binary_hash.update(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading MEV-Boost binary from Github. {exception}')
        return False
    
    checksums_path = download_path.joinpath(checksums_asset['file_name'])
    if checksums_path.is_file():
        checksums_path.unlink()

    try:
        with open(checksums_path, 'wb') as checksums_file:
            with httpx.stream('GET', checksums_asset['file_url'],
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'HTTP error while downloading MEV-Boost checksums from Github. '
                        f'Status code {http_stream.status_code}')
                    return False
                
                archive_filename = checksums_asset['file_name']
                archive_url = checksums_asset['file_url']
                log.info(f'Downloading {archive_filename} from {archive_url} ...')

                for data in http_stream.iter_bytes():
                    checksums_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading MEV-Boost checksums from Github. {exception}')
        return False

    # Verify checksum

    hash_found = False
    with open(checksums_path, 'r') as checksums_file:
        for line in checksums_file:
            result = re.search(r'(?P<hash>[a-fA-F0-9]+)\s+' +
                re.escape(binary_asset['file_name']), line)
            if result:
                hash_found = True
                checksum = result.group('hash').lower()

                binary_hexdigest = binary_hash.hexdigest().lower()

                if checksum != binary_hexdigest:
                    # SHA256 checksum failed
                    log.error(f'SHA256 checksum failed on MEV-Boost binary from '
                        f'Github. Expected {checksum} but we got {binary_hexdigest}. We will '
                        f'stop here to protect you.')
                    return False
                
                log.info('Good SHA256 checksum for MEV-Boost binary.')

                break
    
    if not hash_found:
        archive_filename = binary_asset['file_name']
        log.error(f'We could not find the SHA256 checksum for MEV-Boost binary '
            f'({archive_filename}) in the {checksums_filename} file. We will stop here to '
            f'protect you.')
        return False
    
    # Extracting the MEV-Boost binary archive
    bin_path = base_directory.joinpath('bin')
    bin_path.mkdir(parents=True, exist_ok=True)

    mevboost_service_name = 'mevboost'

    log.info('Stoping MEV-Boost service...')
    subprocess.run([str(nssm_binary), 'stop', mevboost_service_name])

    subprocess.run(['tar', 'xvf', str(binary_path), '--directory', str(bin_path)])
    
    # Remove download leftovers
    binary_path.unlink()
    checksums_path.unlink()

    log.info('Starting MEV-Boost service...')
    subprocess.run([str(nssm_binary), 'start', mevboost_service_name])

    return True

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

def upgrade_nethermind(base_directory, nssm_binary):
    # Upgrade the Nethermind client
    log.info('Upgrading Nethermind client...')

    nethermind_service_name = 'nethermind'
    nethermind_dir = base_directory.joinpath('bin', 'Nethermind')

    log.info('Stoping Nethermind service...')
    subprocess.run([str(nssm_binary), 'stop', nethermind_service_name])

    # Updating Nethermind with winget
    base_options = ['--disable-interactivity', '--accept-source-agreements',
            '--accept-package-agreements']

    try:
        # Update Nethermind
        command = ['winget', 'upgrade', 'nethermind', '-l', str(nethermind_dir)] + base_options

        process_result = subprocess.run(command)
        if process_result.returncode != 0:
            log.error(f'Unexpected return code from winget when installing Nethermind. '
                f'Return code {process_result.returncode}')
            return False

    except FileNotFoundError:
        log.error('winget not found. Aborting.')
        return False

    log.info('Starting Nethermind service...')
    subprocess.run([str(nssm_binary), 'start', nethermind_service_name])

    return True

def upgrade_nimbus(base_directory, nssm_binary):
    # Upgrade the Nimbus client
    log.info('Upgrading Nimbus client...')

    nimbus_gh_release_url = GITHUB_REST_API_URL + NIMBUS_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(nimbus_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading Nimbus binary. {exception}')
        return False

    if response.status_code != 200:
        log.error(f'HTTP error while downloading Nimbus binary. '
            f'Status code {response.status_code}')
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        log.error('No assets in Github release for Nimbus.')
        return False
    
    binary_asset = None

    archive_filename_comp = 'nimbus-eth2_Windows_amd64'

    for asset in release_json['assets']:
        if 'name' not in asset:
            continue
        if 'browser_download_url' not in asset:
            continue
    
        file_name = asset['name']
        file_url = asset['browser_download_url']

        if file_name.startswith(archive_filename_comp):
            binary_asset = {
                'file_name': file_name,
                'file_url': file_url
            }

    if binary_asset is None:
        log.error('Could not find binary in Github release.')
        return False
    
    # Downloading latest Nimbus release files
    download_path = base_directory.joinpath('downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    binary_path = Path(download_path, binary_asset['file_name'])

    try:
        with open(binary_path, 'wb') as binary_file:
            with httpx.stream('GET', binary_asset['file_url'],
                follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error(f'HTTP error while downloading Nimbus binary from Github. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading Nimbus binary from Github. {exception}')
        return False
    
    extract_directory = download_path.joinpath('nimbus')
    if extract_directory.is_dir():
        shutil.rmtree(extract_directory)
    elif extract_directory.is_file():
        os.unlink(extract_directory)
    extract_directory.mkdir(parents=True, exist_ok=True)
    
    # Extracting the Lighthouse binary archive
    subprocess.run([
        'tar', 'xvf', binary_path, '--directory', extract_directory])
    
    # Remove download leftovers
    binary_path.unlink()

    # Find the Nimbus binaries and copy them in their installed location
    build_path = None

    with os.scandir(extract_directory) as it:
        for entry in it:
            if entry.is_dir():
                if entry.name == 'build':
                    build_path = entry.path
                else:
                    build_path = os.path.join(entry.path, 'build')
                break
    
    if build_path is None:
        log.error('Cannot find the correct directory in the extracted Nimbus archive.')
        return False

    src_nimbus_bn_path = Path(build_path, 'nimbus_beacon_node.exe')
    src_nimbus_vc_path = Path(build_path, 'nimbus_validator_client.exe')

    if not src_nimbus_bn_path.is_file() or not src_nimbus_vc_path.is_file():
        log.error(f'Cannot find the Nimbus binaries in the extracted archive.')
        return False
    
    bin_path = base_directory.joinpath('bin')
    bin_path.mkdir(parents=True, exist_ok=True)

    nimbus_service_name = 'nimbus'
    subprocess.run([str(nssm_binary), 'stop', nimbus_service_name])

    dest_nimbus_bn_path = bin_path.joinpath('nimbus_beacon_node.exe')
    dest_nimbus_vc_path = bin_path.joinpath('nimbus_validator_client.exe')
    if dest_nimbus_bn_path.is_file():
        dest_nimbus_bn_path.unlink()
    if dest_nimbus_vc_path.is_file():
        dest_nimbus_vc_path.unlink()

    shutil.move(src_nimbus_bn_path, bin_path)
    shutil.move(src_nimbus_vc_path, bin_path)

    # Remove extraction leftovers
    shutil.rmtree(extract_directory)

    # Make sure Nimbus was installed properly
    nimbus_path = dest_nimbus_bn_path
    nimbus_found = False
    nimbus_version = UNKNOWN_VALUE
    try:
        process_result = subprocess.run([str(nimbus_path), '--version'],
            capture_output=True, text=True)
        nimbus_found = True

        process_output = process_result.stdout
        result = re.search(r'Nimbus beacon node v?(?P<version>[^-]+)', process_output)
        if result:
            nimbus_version = result.group('version').strip()
    except FileNotFoundError:
        pass

    if not nimbus_found:
        log.error(f'We could not find the Nimbus binary from the installed archive '
            f'in {nimbus_path}. We cannot continue.')
        return False
    else:
        log.info(f'Nimbus version {nimbus_version} installed.')

    subprocess.run([str(nssm_binary), 'start', nimbus_service_name])

    return True

def upgrade_lighthouse(base_directory, nssm_binary):
    # Upgrade the Lighthouse client
    log.info('Upgrading Lighthouse client...')

    lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(lighthouse_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading Lighthouse binary. {exception}')
        return False

    if response.status_code != 200:
        log.error(f'HTTP error while downloading Lighthouse binary. '
            f'Status code {response.status_code}')
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        log.error('No assets in Github release for Lighthouse.')
        return False
    
    binary_asset = None
    signature_asset = None

    archive_filename_comp = 'x86_64-windows.tar.gz'

    use_optimized_binary = is_adx_supported(base_directory, log)
    if not use_optimized_binary:
        log.warning('CPU does not support ADX instructions. '
            'Using the portable version for Lighthouse.')
        archive_filename_comp = 'x86_64-windows-portable.tar.gz'
    
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
    download_path = base_directory.joinpath('downloads')
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
    
    if not install_gpg(base_directory):
        return False
    
    # Verify PGP signature
    gpg_binary_path = base_directory.joinpath('bin', 'gpg.exe')

    command_line = [str(gpg_binary_path), '--list-keys', '--with-colons',
        LIGHTHOUSE_PRIME_PGP_KEY_ID]
    process_result = subprocess.run(command_line)
    pgp_key_found = process_result.returncode == 0

    if not pgp_key_found:

        retry_index = 0
        retry_count = 15

        key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
        log.info(f'Downloading Sigma Prime\'s PGP key from {key_server} ...')
        command_line = [str(gpg_binary_path), '--keyserver', key_server,
            '--recv-keys', LIGHTHOUSE_PRIME_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        if process_result.returncode != 0:
            # GPG failed to download PGP key, let's wait and retry a few times
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                delay = 5
                log.warning(f'GPG failed to download the PGP key. We will wait {delay} seconds '
                    f'and try again from a different server.')
                time.sleep(delay)

                key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
                log.info(f'Downloading Sigma Prime\'s PGP key from {key_server} ...')
                command_line = [str(gpg_binary_path), '--keyserver', key_server,
                    '--recv-keys', LIGHTHOUSE_PRIME_PGP_KEY_ID]

                process_result = subprocess.run(command_line)

        if process_result.returncode != 0:
            log.warning(
f'''
We failed to download the Sigma Prime's PGP key to verify the Lighthouse
archive after {retry_count} retries. We will skip signature verification.
'''
            )
        else:
            process_result = subprocess.run([
                str(gpg_binary_path), '--verify', str(signature_path)])
            if process_result.returncode != 0:
                log.error('The Lighthouse archive signature is wrong. We\'ll stop here to protect you.')
                return False
    else:
        process_result = subprocess.run([
            str(gpg_binary_path), '--verify', str(signature_path)])
        if process_result.returncode != 0:
            log.error('The Lighthouse archive signature is wrong. We\'ll stop here to protect you.')
            return False
    
    # Remove download leftovers
    signature_path.unlink()

    bin_path = base_directory.joinpath('bin')
    bin_path.mkdir(parents=True, exist_ok=True)

    lighthouse_bn_service_name = 'lighthousebeacon'
    lighthouse_vc_service_name = 'lighthousevalidator'
    
    subprocess.run([str(nssm_binary), 'stop', lighthouse_bn_service_name])
    subprocess.run([str(nssm_binary), 'stop', lighthouse_vc_service_name])

    # Extracting the Lighthouse binary archive
    subprocess.run([
        'tar', 'xvf', binary_path, '--directory', bin_path])
    
    subprocess.run([str(nssm_binary), 'start', lighthouse_bn_service_name])
    subprocess.run([str(nssm_binary), 'start', lighthouse_vc_service_name])
    
    # Remove download leftovers
    binary_path.unlink()

    lighthouse_path = base_directory.joinpath('bin', 'lighthouse.exe')

    lighthouse_found = False
    lighthouse_version = 'unknown'

    if lighthouse_path.is_file():
        try:
            process_result = subprocess.run([str(lighthouse_path), '--version'],
                capture_output=True, text=True)
            lighthouse_found = True

            process_output = process_result.stdout
            result = re.search(r'Lighthouse v?(?P<version>[^-]+)', process_output)
            if result:
                lighthouse_version = result.group('version').strip()

        except FileNotFoundError:
            pass

    if not lighthouse_found:
        log.error(f'We could not find the Lighthouse binary from the installed archive '
            f'in {lighthouse_path}. We cannot continue.')
        return False
    else:
        log.info(f'Lighthouse version {lighthouse_version} installed.')

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

    teku_arguments = client_details['exec']['argv']

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