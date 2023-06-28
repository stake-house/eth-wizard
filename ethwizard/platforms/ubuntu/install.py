import os
import subprocess
import httpx
import hashlib
import shutil
import time
import humanize
import stat
import json
import re

from datetime import timedelta

from pathlib import Path

from packaging.version import parse as parse_version

from yaml import safe_load

from ethwizard.constants import *

from ethwizard.platforms.common import (
    select_network,
    select_mev_min_bid,
    select_mev_relays,
    select_custom_ports,
    select_eth1_fallbacks,
    select_consensus_checkpoint_provider,
    progress_log_dialog,
    search_for_generated_keys,
    select_consensus_client,
    select_execution_client,
    select_keys_directory,
    select_fee_recipient_address,
    select_withdrawal_address,
    get_bc_validator_deposits,
    test_open_ports,
    show_whats_next,
    show_public_keys,
    Step,
    test_context_variable,
    format_for_terminal
)

from ethwizard.platforms.ubuntu.common import (
    log,
    quit_app,
    get_systemd_service_details,
    is_package_installed,
    is_adx_supported,
    setup_jwt_token_file
)

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog

def installation_steps():

    def test_system_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        want_to_test = CTX_WANT_TO_TEST
        disk_size_tested = CTX_DISK_SIZE_TESTED
        disk_speed_tested = CTX_DISK_SPEED_TESTED
        available_ram_tested = CTX_AVAILABLE_RAM_TESTED
        internet_speed_tested = CTX_INTERNET_SPEED_TESTED

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        if want_to_test not in context:
            context[want_to_test] = show_test_overview(context[selected_network])
            step_sequence.save_state(step.step_id, context)

        if not context[want_to_test]:
            # User asked to quit
            del context[want_to_test]
            step_sequence.save_state(step.step_id, context)

            quit_app()

        if context[want_to_test] == 1:
            if not context.get(disk_size_tested, False):
                if not test_disk_size(context[selected_network]):
                    # User asked to quit
                    quit_app()
                
                context[disk_size_tested] = True
                step_sequence.save_state(step.step_id, context)

            if not context.get(disk_speed_tested, False):
                if not test_disk_speed():
                    # User asked to quit
                    quit_app()
                
                context[disk_speed_tested] = True
                step_sequence.save_state(step.step_id, context)
            
            if not context.get(available_ram_tested, False):
                if not test_available_ram():
                    # User asked to quit
                    quit_app()
                
                context[available_ram_tested] = True
                step_sequence.save_state(step.step_id, context)

            if not context.get(internet_speed_tested, False):
                if not test_internet_speed():
                    # User asked to quit
                    quit_app()
                
                context[internet_speed_tested] = True
                step_sequence.save_state(step.step_id, context)
        
        return context

    test_system_step = Step(
        step_id=TEST_SYSTEM_STEP_ID,
        display_name='Testing your system',
        exc_function=test_system_function
    )

    def select_network_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK

        if selected_network not in context:
            context[selected_network] = select_network(log)
            step_sequence.save_state(step.step_id, context)

        if not context[selected_network]:
            # User asked to quit
            del context[selected_network]
            step_sequence.save_state(step.step_id, context)

            quit_app()
        
        return context
    
    select_network_step = Step(
        step_id=SELECT_NETWORK_STEP_ID,
        display_name='Network selection',
        exc_function=select_network_function
    )

    def select_custom_ports_function(step, context, step_sequence):
        # Context variables
        selected_ports = CTX_SELECTED_PORTS
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT

        if not (
            test_context_variable(context, selected_consensus_client, log) and
            test_context_variable(context, selected_execution_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]
        execution_client = context[selected_execution_client]

        if selected_ports not in context:
            context[selected_ports] = {
                'eth1': DEFAULT_EXECUTION_PORT[execution_client],
                'eth2_bn': DEFAULT_CONSENSUS_PORT[consensus_client]
            }
        
        context[selected_ports] = select_custom_ports(context[selected_ports])
        if not context[selected_ports]:
            # User asked to quit or error
            del context[selected_ports]
            step_sequence.save_state(step.step_id, context)

            quit_app()
        
        return context

    select_custom_ports_step = Step(
        step_id=SELECT_CUSTOM_PORTS_STEP_ID,
        display_name='Open ports configuration',
        exc_function=select_custom_ports_function
    )

    def install_execution_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_ports, log) and
            test_context_variable(context, selected_execution_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        execution_client = context[selected_execution_client]

        if execution_client == EXECUTION_CLIENT_GETH:

            if not install_geth(context[selected_network], context[selected_ports]):
                # User asked to quit or error
                quit_app()
        
        elif execution_client == EXECUTION_CLIENT_NETHERMIND:
        
            if not install_nethermind(context[selected_network], context[selected_ports]):
                # User asked to quit or error
                quit_app()
        
        return context
    
    install_execution_step = Step(
        step_id=INSTALL_EXECUTION_STEP_ID,
        display_name='Execution client installation',
        exc_function=install_execution_function
    )

    def install_mevboost_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        mevboost_installed = CTX_MEVBOOST_INSTALLED

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        installed_value = install_mevboost(context[selected_network])

        if not installed_value:
            # User asked to quit or error
            quit_app()
        
        context[mevboost_installed] = installed_value.get('installed', False)
        
        return context
    
    install_mevboost_step = Step(
        step_id=INSTALL_MEVBOOST_STEP_ID,
        display_name='MEV-Boost installation',
        exc_function=install_mevboost_function
    )

    def detect_merge_ready_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        merge_ready_network = CTX_MERGE_READY_NETWORK

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        context[merge_ready_network] = detect_merge_ready(context[selected_network])
        if not context[merge_ready_network]:
            # User asked to quit or error
            del context[merge_ready_network]
            step_sequence.save_state(step.step_id, context)

            quit_app()
        
        context[merge_ready_network] = context[merge_ready_network]['result']
        
        return context

    detect_merge_ready_step = Step(
        step_id=DETECT_MERGE_READY_STEP_ID,
        display_name='Detect merge ready network',
        exc_function=detect_merge_ready_function
    )

    def select_eth1_fallbacks_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        merge_ready_network = CTX_MERGE_READY_NETWORK
        selected_eth1_fallbacks = CTX_SELECTED_ETH1_FALLBACKS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, merge_ready_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        if not context[merge_ready_network]:
            if selected_eth1_fallbacks not in context:
                context[selected_eth1_fallbacks] = select_eth1_fallbacks(context[selected_network])
                step_sequence.save_state(step.step_id, context)

            if (
                type(context[selected_eth1_fallbacks]) is not list and
                not context[selected_eth1_fallbacks]):
                # User asked to quit
                del context[selected_eth1_fallbacks]
                step_sequence.save_state(step.step_id, context)

                quit_app()
        else:
            context[selected_eth1_fallbacks] = []

        return context

    select_eth1_fallbacks_step = Step(
        step_id=SELECT_ETH1_FALLBACKS_STEP_ID,
        display_name='Adding execution fallback nodes',
        exc_function=select_eth1_fallbacks_function
    )

    def select_consensus_checkpoint_url_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_consensus_checkpoint_url = CTX_SELECTED_CONSENSUS_CHECKPOINT_URL

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        if selected_consensus_checkpoint_url not in context:
            context[selected_consensus_checkpoint_url] = select_consensus_checkpoint_provider(
                context[selected_network], log)
            step_sequence.save_state(step.step_id, context)

        if (
            type(context[selected_consensus_checkpoint_url]) is not str and
            not context[selected_consensus_checkpoint_url]):
            # User asked to quit
            del context[selected_consensus_checkpoint_url]
            step_sequence.save_state(step.step_id, context)

            quit_app()

        return context

    select_consensus_checkpoint_url_step = Step(
        step_id=SELECT_CONSENSUS_CHECKPOINT_URL_STEP_ID,
        display_name='Adding consensus checkpoint state',
        exc_function=select_consensus_checkpoint_url_function
    )

    def install_consensus_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS
        selected_eth1_fallbacks = CTX_SELECTED_ETH1_FALLBACKS
        selected_consensus_checkpoint_url = CTX_SELECTED_CONSENSUS_CHECKPOINT_URL
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
        mevboost_installed = CTX_MEVBOOST_INSTALLED

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_ports, log) and
            test_context_variable(context, selected_eth1_fallbacks, log) and
            test_context_variable(context, selected_consensus_checkpoint_url, log) and
            test_context_variable(context, mevboost_installed, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]

        if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

            if not install_lighthouse(context[selected_network], context[selected_eth1_fallbacks],
                context[selected_consensus_checkpoint_url], context[selected_ports],
                context[mevboost_installed]):
                # User asked to quit or error
                quit_app()

        elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

            if not install_nimbus(context[selected_network], context[selected_eth1_fallbacks],
                context[selected_consensus_checkpoint_url], context[selected_ports],
                context[mevboost_installed]):
                # User asked to quit or error
                quit_app()

        return context
    
    install_consensus_step = Step(
        step_id=INSTALL_CONSENSUS_STEP_ID,
        display_name='Consensus client installation',
        exc_function=install_consensus_function
    )

    def test_open_ports_function(step, context, step_sequence):
        # Context variables
        selected_ports = CTX_SELECTED_PORTS

        if not (
            test_context_variable(context, selected_ports, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        if not test_open_ports(context[selected_ports], log):
            # User asked to quit or error
            quit_app()

        return context

    test_open_ports_step = Step(
        step_id=TEST_OPEN_PORTS_STEP_ID,
        display_name='Testing open ports',
        exc_function=test_open_ports_function
    )

    def obtain_keys_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]

        if obtained_keys not in context:
            context[obtained_keys] = obtain_keys(context[selected_network], consensus_client)
            step_sequence.save_state(step.step_id, context)

        if not context[obtained_keys]:
            # User asked to quit
            del context[obtained_keys]
            step_sequence.save_state(step.step_id, context)

            quit_app()

        return context

    obtain_keys_step = Step(
        step_id=OBTAIN_KEYS_STEP_ID,
        display_name='Importing or generating keys',
        exc_function=obtain_keys_function
    )

    def select_fee_recipient_address_function(step, context, step_sequence):
        # Context variables
        merge_ready_network = CTX_MERGE_READY_NETWORK
        selected_fee_recipient_address = CTX_SELECTED_FEE_RECIPIENT_ADDRESS
        
        if not (
            test_context_variable(context, merge_ready_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        if context[merge_ready_network]:
            if selected_fee_recipient_address not in context:
                context[selected_fee_recipient_address] = select_fee_recipient_address()
                step_sequence.save_state(step.step_id, context)

            if not context[selected_fee_recipient_address]:
                # User asked to quit
                del context[selected_fee_recipient_address]
                step_sequence.save_state(step.step_id, context)

                quit_app()
        else:
            context[selected_fee_recipient_address] = ''

        return context

    select_fee_recipient_address_step = Step(
        step_id=SELECT_FEE_RECIPIENT_ADDRESS_STEP_ID,
        display_name='Select your fee recipient address',
        exc_function=select_fee_recipient_address_function
    )

    def install_validator_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS       
        selected_fee_recipient_address = CTX_SELECTED_FEE_RECIPIENT_ADDRESS
        public_keys = CTX_PUBLIC_KEYS
        mevboost_installed = CTX_MEVBOOST_INSTALLED
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, selected_fee_recipient_address, log) and
            test_context_variable(context, mevboost_installed, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]

        if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

            context[public_keys] = install_lighthouse_validator(context[selected_network],
                context[obtained_keys], context[selected_fee_recipient_address],
                context[mevboost_installed])

        elif consensus_client == CONSENSUS_CLIENT_NIMBUS:
            # Install Nimbus validator client
            context[public_keys] = install_nimbus_validator(context[selected_network],
                context[obtained_keys], context[selected_fee_recipient_address],
                context[mevboost_installed])

        if type(context[public_keys]) is not list and not context[public_keys]:
            # User asked to quit
            del context[public_keys]
            step_sequence.save_state(step.step_id, context)

            quit_app()

        return context
    
    install_validator_step = Step(
        step_id=INSTALL_VALIDATOR_STEP_ID,
        display_name='Validator client installation',
        exc_function=install_validator_function
    )

    def install_chrony_function(step, context, step_sequence):
        if not install_chrony():
            # User asked to quit or error
            quit_app()

        return context

    install_chrony_step = Step(
        step_id=INSTALL_CHRONY_STEP_ID,
        display_name='Install chrony',
        exc_function=install_chrony_function
    )

    def initiate_deposit_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]

        if not initiate_deposit(context[selected_network], context[obtained_keys],
            consensus_client):
            # User asked to quit
            quit_app()

        return context

    initiate_deposit_step = Step(
        step_id=INITIATE_DEPOSIT_STEP_ID,
        display_name='Deposit on the launchpad',
        exc_function=initiate_deposit_function
    )

    def show_whats_next_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        public_keys = CTX_PUBLIC_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, public_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        show_whats_next(context[selected_network], context[public_keys])

        return context
    
    show_whats_next_step = Step(
        step_id=SHOW_WHATS_NEXT_STEP_ID,
        display_name='Installation completed',
        exc_function=show_whats_next_function
    )

    def show_public_keys_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        public_keys = CTX_PUBLIC_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, public_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        show_public_keys(context[selected_network], context[public_keys], log)

        return context
    
    show_public_keys_step = Step(
        step_id=SHOW_PUBLIC_KEYS_STEP_ID,
        display_name='Show public keys',
        exc_function=show_public_keys_function
    )

    def select_consensus_client_function(step, context, step_sequence):
        # Context variables
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        consensus_client = select_consensus_client(SUPPORTED_LINUX_CONSENSUS_CLIENTS)

        if not consensus_client:
            quit_app()
        
        context[selected_consensus_client] = consensus_client

        return context
    
    select_consensus_client_step = Step(
        step_id=SELECT_CONSENSUS_CLIENT_STEP_ID,
        display_name='Select consensus client',
        exc_function=select_consensus_client_function
    )

    def select_execution_client_function(step, context, step_sequence):
        # Context variables
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT

        execution_client = select_execution_client(SUPPORTED_LINUX_EXECUTION_CLIENTS)

        if not execution_client:
            quit_app()
        
        context[selected_execution_client] = execution_client

        return context
    
    select_execution_client_step = Step(
        step_id=SELECT_EXECUTION_CLIENT_STEP_ID,
        display_name='Select execution client',
        exc_function=select_execution_client_function
    )

    return [
        select_network_step,
        select_consensus_client_step,
        select_execution_client_step,
        test_system_step,
        install_mevboost_step,
        select_custom_ports_step,
        detect_merge_ready_step,
        select_consensus_checkpoint_url_step,
        select_eth1_fallbacks_step,
        install_consensus_step,
        install_execution_step,
        test_open_ports_step,
        obtain_keys_step,
        select_fee_recipient_address_step,
        install_validator_step,
        install_chrony_step,
        # TODO: Monitoring setup
        initiate_deposit_step,
        show_whats_next_step,
        show_public_keys_step
    ]

def show_test_overview(network):
    # Show the overall tests to perform

    result = button_dialog(
        title='Testing your system',
        text=(
f'''
We can test your system to make sure it is fit for being a validator. Here
is the list of tests we will perform:

* Disk size (>= {MIN_AVAILABLE_DISK_SPACE_GB[network]:.0f}GB of available space for {NETWORK_LABEL[network]})
* Disk speed (>= {MIN_SUSTAINED_K_READ_IOPS:.1f}K sustained read IOPS and >= {MIN_SUSTAINED_K_WRITE_IOPS:.1f}K sustained write IOPS)
* Memory size (>= {MIN_AVAILABLE_RAM_GB:.1f}GB of available RAM)
* Internet speed (>= {MIN_DOWN_MBS:.1f}MB/s down and >= {MIN_UP_MBS:.1f}MB/s up)

Do you want to test your system?
'''     ),
        buttons=[
            ('Test', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    return result

def test_disk_size(network):
    # Test disk size

    log.info('Running df to test disk size...')
    process_result = subprocess.run([
        'df', '-h', '--output=avail', '-B1MB', '/var/lib'
        ], capture_output=True, text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unable to test disk size. Return code {process_result.returncode}.\n'
            f'StdOut: {process_result.stdout}\nStdErr: {process_result.stderr}')
        return False
    
    process_output = process_result.stdout
    result = re.search(r'(\d+)', process_output)
    available_space_gb = None
    if result:
        available_space_gb = int(result.group(1)) / 1000.0

    if available_space_gb is None:
        log.error(f'Unable to test disk size. Unexpected output from df command. '
            f'Output: {process_output}')
        return False

    if not available_space_gb >= MIN_AVAILABLE_DISK_SPACE_GB[network]:
        result = button_dialog(
            title=HTML('Disk size test <style bg="red" fg="black">failed</style>'),
            text=(HTML(
f'''
Your available space results seem to indicate that <style bg="red" fg="black">your disk size is
<b>smaller than</b> what would be required</style> to be a fully working validator. Here are
your results:

* Available space in /var/lib: {available_space_gb:.1f}GB (>= {MIN_AVAILABLE_DISK_SPACE_GB[network]:.1f}GB for {NETWORK_LABEL[network]})

It might still be possible to be a validator but you should consider a
larger disk for your system.
'''         )),
            buttons=[
                ('Keep going', True),
                ('Quit', False)
            ]
        ).run()

        return result

    result = button_dialog(
        title=HTML('Disk size test <style bg="green" fg="white">passed</style>'),
        text=(HTML(
f'''
Your available space results seem to indicate that <style bg="green" fg="white">your disk size is <b>large
enough</b></style> to be a fully working validator. Here are your results:

* Available space in /var/lib: {available_space_gb:.1f}GB (>= {MIN_AVAILABLE_DISK_SPACE_GB[network]:.1f}GB for {NETWORK_LABEL[network]})
'''     )),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def test_disk_speed():
    # Test disk speed using fio tool

    # Install fio using APT
    fio_package_installed = False
    try:
        fio_package_installed = is_package_installed('fio')
    except Exception:
        return False
    
    if not fio_package_installed:
        log.info('Installing fio to test disk speed...')

        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'fio'])
    
    # Run fio test
    fio_path = Path(Path.home(), 'ethwizard', 'fio')
    fio_path.mkdir(parents=True, exist_ok=True)

    fio_target_filename = 'random_read_write.fio'
    fio_output_filename = 'fio.out'

    fio_target_path = Path(fio_path, fio_target_filename)
    fio_output_path = Path(fio_path, fio_output_filename)

    log.info('Executing fio to test disk speed...')

    process_result = subprocess.run([
        'fio', '--randrepeat=1', '--ioengine=libaio', '--direct=1', '--gtod_reduce=1',
        '--name=test', '--filename=' + fio_target_filename, '--bs=4k', '--iodepth=64',
        '--size=4G', '--readwrite=randrw', '--rwmixread=75', '--output=' + fio_output_filename,
        '--output-format=json'
        ], cwd=fio_path)

    if process_result.returncode != 0:
        log.error(f'Error while running fio disk test. Return code {process_result.returncode}\n'
            f'StdOut: {process_result.stdout}\nStdErr: {process_result.stderr}')
        return False
    
    # Remove test file
    fio_target_path.unlink()

    results_json = None

    with open(fio_output_path, 'r') as output_file:
        results_json = json.loads(output_file.read(8 * 1024 * 20))

    # Remove test results
    fio_output_path.unlink()

    if results_json is None:
        log.error('Could not read the results from fio output file.')
        return False
    
    if 'jobs' not in results_json or type(results_json['jobs']) is not list:
        log.error('Unexpected structure from fio output file. No jobs list.')
        return False
    
    jobs = results_json['jobs']

    # Find our test job and the results
    test_job = None
    for job in jobs:
        if 'jobname' not in job:
            log.error('Unexpected structure from fio output file. No jobname in a job.')
            return False
        jobname = job['jobname']
        if jobname == 'test':
            test_job = job
            break

    if test_job is None:
        log.error('Unable to find our test job in fio output file.')
        return False
    
    if not (
        'read' in test_job and
        'iops' in test_job['read'] and
        type(test_job['read']['iops']) is float and
        'write' in test_job and
        'iops' in test_job['write'] and
        type(test_job['write']['iops']) is float):
        log.error('Unexpected structure from fio output file. No read or write iops.')
        return False
    
    k_read_iops = test_job['read']['iops'] / 1000.0
    k_write_iops = test_job['write']['iops'] / 1000.0

    # Test if disk speed is above minimal values
    if not (
        k_read_iops >= MIN_SUSTAINED_K_READ_IOPS and
        k_write_iops >= MIN_SUSTAINED_K_WRITE_IOPS):

        result = button_dialog(
            title=HTML('Disk speed test <style bg="red" fg="black">failed</style>'),
            text=(HTML(
f'''
Your disk speed results seem to indicate that <style bg="red" fg="black">your disk is <b>slower than</b>
what would be required</style> to be a fully working validator. Here are your
results:

* Read speed: {k_read_iops:.1f}K read IOPS (>= {MIN_SUSTAINED_K_READ_IOPS:.1f}K sustained read IOPS)
* Write speed: {k_write_iops:.1f}K write IOPS (>= {MIN_SUSTAINED_K_WRITE_IOPS:.1f}K sustained write IOPS)

It might still be possible to be a validator but you should consider a
faster disk.
'''         )),
            buttons=[
                ('Keep going', True),
                ('Quit', False)
            ]
        ).run()

        return result

    result = button_dialog(
        title=HTML('Disk speed test <style bg="green" fg="white">passed</style>'),
        text=(HTML(
f'''
Your disk speed results seem to indicate that <style bg="green" fg="white">your disk is <b>fast enough</b></style> to
be a fully working validator. Here are your results:

* Read speed: {k_read_iops:.1f}K read IOPS (>= {MIN_SUSTAINED_K_READ_IOPS:.1f}K sustained read IOPS)
* Write speed: {k_write_iops:.1f}K write IOPS (>= {MIN_SUSTAINED_K_WRITE_IOPS:.1f}K sustained write IOPS)
'''     )),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def test_internet_speed():
    # Test for internet speed

    # Downloading speedtest script
    log.info('Downloading speedtest-cli script to test internet speed...')
    download_path = Path(Path.home(), 'ethwizard', 'downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    script_path = Path(download_path, 'speedtest-cli.py')

    try:
        with open(script_path, 'wb') as binary_file:
            with httpx.stream('GET', SPEEDTEST_SCRIPT_URL, follow_redirects=True) as http_stream:
                if http_stream.status_code != 200:
                    log.error('HTTP error while downloading speedtest-cli script. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading speedtest-cli script. {exception}')
        return False
    
    # Setup to run the speedtest script with an unprivileged user
    ethwizardnopriv_user_exists = False
    process_result = subprocess.run([
        'id', '-u', 'ethwizardnopriv'
    ])
    ethwizardnopriv_user_exists = (process_result.returncode == 0)

    # Setup ethwizardnopriv user
    if not ethwizardnopriv_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', 'ethwizardnopriv'])

    tmp_script_path = Path('/tmp', 'speedtest-cli.py')

    subprocess.run([
        'cp', script_path, tmp_script_path])
    subprocess.run([
        'chown', 'ethwizardnopriv:ethwizardnopriv', tmp_script_path])

    # Run speedtest script
    log.info('Running speedtest to test internet speed...')

    process_result = subprocess.run([
        'sudo', '-u', 'ethwizardnopriv', '-g', 'ethwizardnopriv', 'python3', tmp_script_path, '--secure', '--json'
        ], capture_output=True, text=True)

    # Remove download leftovers
    tmp_script_path.unlink()
    script_path.unlink()

    if process_result.returncode != 0:
        log.error(f'Unable to run speedtest script. Return code {process_result.returncode}\n'
            f'StdOut: {process_result.stdout}\nStdErr: {process_result.stderr}')
        return False

    process_output = process_result.stdout
    speedtest_results = json.loads(process_output)

    if (
        'download' not in speedtest_results or
        type(speedtest_results['download']) is not float or
        'upload' not in speedtest_results or
        type(speedtest_results['upload']) is not float
    ):
        log.error(f'Unexpected response from speedtest. \n {speedtest_results}')
        return False
    
    down_mbs = speedtest_results['download'] / 1000000.0 / 8.0
    up_mbs = speedtest_results['upload'] / 1000000.0 / 8.0
    speedtest_server = speedtest_results.get('server', None)
    server_sponsor = 'unknown'
    server_name = 'unknown'
    server_country = 'unknown'
    server_lat = 'unknown'
    server_lon = 'unknown'

    if speedtest_server is not None:
        server_sponsor = speedtest_server.get('sponsor', 'unknown')
        server_name = speedtest_server.get('name', 'unknown')
        server_country = speedtest_server.get('country', 'unknown')
        server_lat = speedtest_server.get('lat', 'unknown')
        server_lon = speedtest_server.get('lon', 'unknown')

    # Test if Internet speed is above minimal values
    if not (down_mbs >= MIN_DOWN_MBS and up_mbs >= MIN_UP_MBS):

        result = button_dialog(
            title=HTML('Internet speed test <style bg="red" fg="black">failed</style>'),
            text=(HTML(
f'''
Your speedtest results seem to indicate that <style bg="red" fg="black">your Internet speed is <b>slower
than</b> what would be required</style> to be a fully working validator. Here are your
results:

* Download speed: {down_mbs:.1f}MB/s (>= {MIN_DOWN_MBS:.1f}MB/s)
* Upload speed: {up_mbs:.1f}MB/s (>= {MIN_UP_MBS:.1f}MB/s)
* Server sponsor: {server_sponsor}
* Server name: {server_name}
* Server country: {server_country}
* Server location: {server_lat}, {server_lon}

It might still be possible to be a validator but you should consider an
improved Internet plan or a different Internet service provider.
'''         )),
            buttons=[
                ('Keep going', True),
                ('Quit', False)
            ]
        ).run()

        return result

    result = button_dialog(
        title=HTML('Internet speed test <style bg="green" fg="white">passed</style>'),
        text=(HTML(
f'''
Your speedtest results seem to indicate that <style bg="green" fg="white">your Internet speed is <b>fast
enough</b></style> to be a fully working validator. Here are your results:

* Download speed: {down_mbs:.1f}MB/s (>= {MIN_DOWN_MBS:.1f}MB/s)
* Upload speed: {up_mbs:.1f}MB/s (>= {MIN_UP_MBS:.1f}MB/s)
* Server sponsor: {server_sponsor}
* Server name: {server_name}
* Server country: {server_country}
* Server location: {server_lat}, {server_lon}
'''     )),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def test_available_ram():
    # Test available RAM

    log.info('Inspecting /proc/meminfo for available RAM...')
    process_result = subprocess.run([
        'grep', 'MemTotal', '/proc/meminfo'
        ], capture_output=True, text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unable to get available total RAM. Return code {process_result.returncode}\n'
            f'StdOut: {process_result.stdout}\nStdErr: {process_result.stderr}')
        return False
    
    process_output = process_result.stdout

    total_available_ram_gb = 0.0

    result = re.search(r'MemTotal:\s*(?P<memkb>\d+) kB', process_output)
    if result:
        total_available_ram_gb = int(result.group('memkb')) / 1000000.0
    else:
        log.error(f'Unable to parse the output of /proc/meminfo to get available total RAM. '
            f'Output: {process_output}')
        return False
    
    # Test if available RAM is above minimal values
    if not total_available_ram_gb >= MIN_AVAILABLE_RAM_GB:

        result = button_dialog(
            title=HTML('Memory size test <style bg="red" fg="black">failed</style>'),
            text=(HTML(
f'''
Your memory size results seem to indicate that <style bg="red" fg="black">your available RAM is <b>lower
than</b> what would be required</style> to be a fully working validator. Here are your
results:

* Memory size: {total_available_ram_gb:.1f}GB of available RAM (>= {MIN_AVAILABLE_RAM_GB:.1f}GB of available RAM)

It might still be possible to be a validator but you should consider having
more memory.
'''         )),
            buttons=[
                ('Keep going', True),
                ('Quit', False)
            ]
        ).run()

        return result

    result = button_dialog(
        title=HTML('Memory size test <style bg="green" fg="white">passed</style>'),
        text=(HTML(
f'''
Your memory size results seem to indicate that <style bg="green" fg="white">your available RAM is <b>large
enough</b></style> to be a fully working validator. Here are your results:

* Memory size: {total_available_ram_gb:.1f}GB of available RAM (>= {MIN_AVAILABLE_RAM_GB:.1f}GB of available RAM)
'''     )),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def install_mevboost(network):
    # Install mev-boost for the selected network

    installed_value = {
        'installed': False
    }

    # Check for existing systemd service
    mevboost_service_exists = False
    mevboost_service_name = MEVBOOST_SYSTEMD_SERVICE_NAME

    service_details = get_systemd_service_details(mevboost_service_name)

    if service_details['LoadState'] == 'loaded':
        mevboost_service_exists = True
    
    if mevboost_service_exists:
        result = button_dialog(
            title='MEV-Boost service found',
            text=(
f'''
The MEV-Boost service seems to have already been created. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to keep the current MEV-Boost service?
'''         ),
            buttons=[
                ('Keep', 1),
                ('Reinstall', 2),
                ('Remove', 3),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            installed_value['installed'] = True
            return installed_value

        if result == 3:
            subprocess.run([
                'systemctl', 'stop', mevboost_service_name])
            os.unlink('/etc/systemd/system/' + mevboost_service_name)
            subprocess.run([
                'systemctl', 'daemon-reload'])

            installed_value['installed'] = False
            return installed_value
        
        # User wants to proceed, make sure the mev-boost service is stopped first
        subprocess.run([
            'systemctl', 'stop', mevboost_service_name])
    
    result = button_dialog(
        title='MEV-Boost installation',
        text=(
'''
You can decide to install MEV-Boost to obtain additional rewards. This is
entirely optional. However, if you want to maximize your profits, you
should consider installing it.

You can learn more on https://ethereum.org/en/developers/docs/mev/ and on
https://writings.flashbots.net/why-run-mevboost/ .

It will download the official binary from GitHub and extract it for easy
use. It will be configured with a few options in the next steps.

Once installed locally, it will create a systemd service that will
automatically start MEV-Boost on reboot or if it crashes.
'''     ),
        buttons=[
            ('Install', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    if result == 2:
        return installed_value
    
    # Check if mev-boost is already installed
    mevboost_found = False
    mevboost_version = 'unknown'
    mevboost_location = 'unknown'

    try:
        process_result = subprocess.run([
            'mev-boost', '--version'
            ], capture_output=True, text=True)
        mevboost_found = True

        process_output = process_result.stdout
        result = re.search(r'mev-boost v?(\S+)', process_output)
        if result:
            mevboost_version = result.group(1).strip()
        
        process_result = subprocess.run([
            'whereis', 'mev-boost'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'mev-boost: (.*?)\n', process_output)
        if result:
            mevboost_location = result.group(1).strip()

    except FileNotFoundError:
        pass
    
    install_mevboost_binary = True

    if mevboost_found:
        result = button_dialog(
            title='MEV-Boost binary found',
            text=(
f'''
The MEV-Boost binary seems to have already been installed. Here are some
details found:

Version: {mevboost_version}
Location: {mevboost_location}

Do you want to skip installing the MEV-Boost binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_mevboost_binary = (result == 2)

    if install_mevboost_binary:
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

        archive_filename_comp = 'linux_amd64.tar.gz'
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
        download_path = Path(Path.home(), 'ethwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])
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
        
        checksums_path = Path(download_path, checksums_asset['file_name'])

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
        subprocess.run([
            'tar', 'xvf', binary_path, '--directory', MEVBOOST_INSTALLED_DIRECTORY])
        
        # Remove download leftovers
        binary_path.unlink()
        checksums_path.unlink()

        # Get MEV-Boost version
        try:
            process_result = subprocess.run([
            'mev-boost', '--version'
            ], capture_output=True, text=True)
            mevboost_found = True

            process_output = process_result.stdout
            result = re.search(r'mev-boost v?(\S+)', process_output)
            if result:
                mevboost_version = result.group(1).strip()
        except FileNotFoundError:
            pass

    addparams = []

    # Select a min-bid value

    min_bid = select_mev_min_bid(log)

    if min_bid is False or min_bid is None:
        return False

    if min_bid > 0:
        min_bid_value = f'{min_bid:.6f}'.rstrip('0').rstrip('.')
        addparams.append(f'-min-bid {min_bid_value}')

    # Select relays

    relay_list = select_mev_relays(network, log)

    if not relay_list:
        return False

    for relay in relay_list:
        addparams.append(f'-relay {relay}')

    mevboost_user_exists = False
    process_result = subprocess.run([
        'id', '-u', 'mevboost'
    ])
    mevboost_user_exists = (process_result.returncode == 0)

    # Setup MEV-Boost user

    if not mevboost_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', 'mevboost'])
    
    # Setup MEV-Boost systemd service

    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' \\\n    ' + ' \\\n    '.join(addparams)

    with open('/etc/systemd/system/' + mevboost_service_name, 'w') as service_file:
        service_file.write(MEVBOOST_SERVICE_DEFINITION[network].format(addparams=addparams_string))
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', mevboost_service_name])
    subprocess.run([
        'systemctl', 'enable', mevboost_service_name])
    
    # Wait a little before checking for MEV-Boost
    delay = 6
    log.info(f'We are giving MEV-Boost {delay} seconds to start before testing it.')
    time.sleep(delay)

    # Verify proper MEV-Boost service installation
    service_details = get_systemd_service_details(mevboost_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='MEV-Boost service not running properly',
            text=(
f'''
The MEV-Boost service we just created seems to have issues. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the MEV-Boost service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see
the logs with:

$ sudo journalctl -ru {mevboost_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your MEV-Boost service logs, type the following command:

$ sudo journalctl -ru {mevboost_service_name}
'''
        )

        return False
    
    log.info(
f'''
MEV-Boost version {mevboost_version} is installed and working properly.
''' )
    time.sleep(5)

    installed_value['installed'] = True
    return installed_value

def install_geth(network, ports):
    # Install Geth for the selected network

    # Check for existing systemd service
    geth_service_exists = False
    geth_service_name = GETH_SYSTEMD_SERVICE_NAME

    service_details = get_systemd_service_details(geth_service_name)

    if service_details['LoadState'] == 'loaded':
        geth_service_exists = True
    
    if geth_service_exists:
        result = button_dialog(
            title='Geth service found',
            text=(
f'''
The Geth service seems to have already been created. Here are some details
found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to skip installing Geth and its service?
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
        
        # User wants to proceed, make sure the Geth service is stopped first
        subprocess.run([
            'systemctl', 'stop', geth_service_name])

    result = button_dialog(
        title='Geth installation',
        text=(
'''
This next step will install Geth, an Ethereum execution client.

It uses the official Ethereum Personal Package Archive (PPA) meaning that
it gets integrated with the normal updates for Ubuntu and its related
tools like APT.

Once the installation is completed, it will create a systemd service that
will automatically start Geth on reboot or if it crashes. Geth will be
started and you will slowly start syncing with the Ethereum network. This
syncing process can take a few hours or days even with good hardware and
good internet. We will perform a few tests to make sure Geth is running
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
    geth_found = False
    geth_package_installed = False
    installed_from_ppa = False
    geth_version = 'unknown'
    geth_location = 'unknown'

    try:
        process_result = subprocess.run([
            'geth', 'version'
            ], capture_output=True, text=True)
        geth_found = True

        process_output = process_result.stdout
        result = re.search(r'Version: (.*?)\n', process_output)
        if result:
            geth_version = result.group(1).strip()
        
        process_result = subprocess.run([
            'whereis', 'geth'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'geth: (.*?)\n', process_output)
        if result:
            geth_location = result.group(1).strip()

        geth_package_installed = False
        try:
            geth_package_installed = is_package_installed('geth')
        except Exception:
            return False

        if geth_package_installed:
            # Geth package is installed
            process_result = subprocess.run([
                'apt', 'show', 'geth'
                ], capture_output=True, text=True)
            
            process_output = process_result.stdout
            result = re.search(r'APT-Sources: (.*?)\n', process_output)
            if result:
                apt_sources = result.group(1).strip()
                apt_sources_splits = apt_sources.split(' ')
                if apt_sources_splits[0] == ETHEREUM_APT_SOURCE_URL:
                    installed_from_ppa = True

    except FileNotFoundError:
        pass
    
    install_geth_binary = True

    if geth_found:
        result = button_dialog(
            title='Geth binary found',
            text=(
f'''
The Geth binary seems to have already been installed. Here are some
details found:

Version: {geth_version}
Location: {geth_location}
Installed from package: {geth_package_installed}
Installed from official Ethereum PPA: {installed_from_ppa}

Do you want to skip installing the Geth binary?
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
        # Install Geth from PPA
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

        subprocess.run([
            'add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'geth'])
        
        # Get Geth version
        try:
            process_result = subprocess.run([
                'geth', 'version'
                ], capture_output=True, text=True)
            geth_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (.*?)\n', process_output)
            if result:
                geth_version = result.group(1).strip()
        except FileNotFoundError:
            pass
    
    # Check if Geth user or directory already exists
    geth_datadir = Path('/var/lib/goethereum')
    if geth_datadir.is_dir():
        process_result = subprocess.run([
            'du', '-sh', geth_datadir
            ], capture_output=True, text=True)
        
        process_output = process_result.stdout
        geth_datadir_size = process_output.split('\t')[0]

        result = button_dialog(
            title='Geth data directory found',
            text=(
f'''
An existing Geth data directory has been found. Here are some
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

    geth_user_exists = False
    process_result = subprocess.run([
        'id', '-u', 'goeth'
    ])
    geth_user_exists = (process_result.returncode == 0)

    # Setup Geth user and directory
    if not geth_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', 'goeth'])
    subprocess.run([
        'mkdir', '-p', geth_datadir])
    subprocess.run([
        'chown', '-R', 'goeth:goeth', geth_datadir])

    addparams = []

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', geth_version)
    if result:
        cleaned_geth_version = parse_version(result.group(1).strip())
        target_geth_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][EXECUTION_CLIENT_GETH])
        
        if cleaned_geth_version >= target_geth_version:
            merge_ready = True
    
    if merge_ready:
        if not setup_jwt_token_file():
            log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
            )

            return False
        
        addparams.append(f'--authrpc.jwtsecret {LINUX_JWT_TOKEN_FILE_PATH}')
    
    # Setup Geth systemd service
    if ports['eth1'] != DEFAULT_GETH_PORT:
        addparams.append(f'--port {ports["eth1"]}')
    
    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' ' + ' '.join(addparams)

    with open('/etc/systemd/system/' + geth_service_name, 'w') as service_file:
        service_file.write(GETH_SERVICE_DEFINITION[network].format(addparams=addparams_string))
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', geth_service_name])
    subprocess.run([
        'systemctl', 'enable', geth_service_name])
    
    # Wait a little before checking for Geth syncing since it can be slow to start
    delay = 30
    log.info(f'We are giving Geth {delay} seconds to start before testing it.')
    time.sleep(delay)

    # Verify proper Geth service installation
    service_details = get_systemd_service_details(geth_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Geth service not running properly',
            text=(
f'''
The Geth service we just created seems to have issues. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the Geth service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False

    # Verify Geth JSON-RPC response
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
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to Geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the Geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Geth',
            text=(
f'''
We could not connect to Geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the Geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False
    
    # Verify proper Geth syncing
    def verifying_callback(set_percentage, log_text, change_status, set_result, get_exited):
        exe_is_working = False
        exe_is_syncing = False
        exe_has_few_peers = False
        exe_connected_peers = 0
        exe_starting_block = UNKNOWN_VALUE
        exe_current_block = UNKNOWN_VALUE
        exe_highest_block = UNKNOWN_VALUE

        set_result({
            'exe_is_working': exe_is_working,
            'exe_is_syncing': exe_is_syncing,
            'exe_starting_block': exe_starting_block,
            'exe_current_block': exe_current_block,
            'exe_highest_block': exe_highest_block,
            'exe_connected_peers': exe_connected_peers
        })

        set_percentage(10)

        journalctl_cursor = None

        while True:

            if get_exited():
                return {
                    'exe_is_working': exe_is_working,
                    'exe_is_syncing': exe_is_syncing,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers
                }

            # Output logs
            command = []
            first_display = True
            if journalctl_cursor is None:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q', '-n', '25',
                    '-o', 'cat', '-u', geth_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '-o', 'cat', '--after-cursor=' + journalctl_cursor, '-u', geth_service_name]
                first_display = False

            process_result = subprocess.run(command, capture_output=True, text=True)

            process_output = ''
            if process_result.returncode == 0:
                process_output = process_result.stdout
            else:
                log_text(f'Return code: {process_result.returncode} while calling journalctl.')

            # Parse journalctl cursor and remove it from process_output
            log_length = len(process_output)
            if log_length > 0:
                result = re.search(r'-- cursor: (?P<cursor>[^\n]+)', process_output)
                if result:
                    journalctl_cursor = result.group('cursor')
                    process_output = (
                        process_output[:result.start()] +
                        process_output[result.end():])
                    process_output = process_output.rstrip()
            
                    log_length = len(process_output)

            if log_length > 0:
                if not first_display and process_output[0] != '\n':
                    process_output = '\n' + process_output
                log_text(process_output)

            time.sleep(1)
            
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
                log_text(f'Exception: {exception} while querying Geth.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Geth.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            local_geth_jsonrpc_url = 'http://127.0.0.1:8545'
            request_json = {
                'jsonrpc': '2.0',
                'method': 'net_peerCount',
                'id': 1
            }
            headers = {
                'Content-Type': 'application/json'
            }
            try:
                response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Geth.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Geth.')
                continue

            response_json = response.json()
            peer_count_json = response_json

            exe_starting_block = UNKNOWN_VALUE
            exe_current_block = UNKNOWN_VALUE
            exe_highest_block = UNKNOWN_VALUE
            if (
                syncing_json and
                'result' in syncing_json and
                syncing_json['result']
                ):
                exe_is_syncing = True
                if 'startingBlock' in syncing_json['result']:
                    exe_starting_block = int(syncing_json['result']['startingBlock'], 16)
                if 'currentBlock' in syncing_json['result']:
                    exe_current_block = int(syncing_json['result']['currentBlock'], 16)
                if 'highestBlock' in syncing_json['result']:
                    exe_highest_block = int(syncing_json['result']['highestBlock'], 16)
            else:
                exe_is_syncing = False

            exe_connected_peers = 0
            if (
                peer_count_json and
                'result' in peer_count_json and
                peer_count_json['result']
                ):
                exe_connected_peers = int(peer_count_json['result'], 16)
            
            exe_has_few_peers = exe_connected_peers >= EXE_MIN_FEW_PEERS

            if exe_is_syncing or exe_has_few_peers:
                set_percentage(100)
            else:
                set_percentage(10 +
                    round(min(exe_connected_peers / EXE_MIN_FEW_PEERS, 1.0) * 90.0))

            change_status((
f'''
Syncing: {exe_is_syncing} (Starting: {exe_starting_block}, Current: {exe_current_block}, Highest: {exe_highest_block})
Connected Peers: {exe_connected_peers}
'''         ).strip())

            if exe_is_syncing or exe_has_few_peers:
                exe_is_working = True
                return {
                    'exe_is_working': exe_is_working,
                    'exe_is_syncing': exe_is_syncing,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers
                }
            else:
                set_result({
                    'exe_is_working': exe_is_working,
                    'exe_is_syncing': exe_is_syncing,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers
                })

    result = progress_log_dialog(
        title='Verifying proper Geth service installation',
        text=(
f'''
We are waiting for Geth to sync or find enough peers to confirm that it is
working properly.
'''     ),
        status_text=(
'''
Syncing: Unknown (Starting: Unknown, Current: Unknown, Highest: Unknown)
Connected Peers: Unknown
'''
        ).strip(),
        with_skip=True,
        run_callback=verifying_callback
    ).run()
    
    if not result:
        log.warning('Geth verification was cancelled.')
        return False

    if result.get('skipping', False):
        log.warning('Skipping Geth verification.')
        return True

    if not result['exe_is_working']:
        # We could not get a proper result from Geth
        result = button_dialog(
            title='Geth verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the Geth installation.
Here are some results for the last tests we performed:

Syncing: {result['exe_is_syncing']} (Starting: {result['exe_starting_block']}, Current: {result['exe_current_block']}, Highest: {result['exe_highest_block']})
Connected Peers: {result['exe_connected_peers']}

We cannot proceed if Geth is not installed properly. Make sure to check the
logs and fix any issue found there. You can see the logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False
    
    log.info(
f'''
Geth is installed and working properly.

Syncing: {result['exe_is_syncing']} (Starting: {result['exe_starting_block']}, Current: {result['exe_current_block']}, Highest: {result['exe_highest_block']})
Connected Peers: {result['exe_connected_peers']}
''' )
    time.sleep(5)

    return True

def install_nethermind(network, ports):
    # Install Nethermind for the selected network

    # Check for existing systemd service
    nethermind_service_exists = False
    nethermind_service_name = NETHERMIND_SYSTEMD_SERVICE_NAME

    service_details = get_systemd_service_details(nethermind_service_name)

    if service_details['LoadState'] == 'loaded':
        nethermind_service_exists = True
    
    if nethermind_service_exists:
        result = button_dialog(
            title='Nethermind service found',
            text=(
f'''
The Nethermind service seems to have already been created. Here are some details
found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to skip installing Nethermind and its service?
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
        
        # User wants to proceed, make sure the Nethermind service is stopped first
        subprocess.run([
            'systemctl', 'stop', nethermind_service_name])

    result = button_dialog(
        title='Nethermind installation',
        text=(
'''
This next step will install Nethermind, an Ethereum execution client.

It uses the Nethermind Personal Package Archive (PPA) meaning that it
gets integrated with the normal updates for Ubuntu and its related tools
like APT.

Once the installation is completed, it will create a systemd service that
will automatically start Nethermind on reboot or if it crashes.
Nethermind will be started and you will slowly start syncing with the
Ethereum network. This syncing process can take a few hours or days even
with good hardware and good internet. We will perform a few tests to make
sure Nethermind is running properly.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if Nethermind is already installed
    nethermind_found = False
    nethermind_package_installed = False
    installed_from_ppa = False
    nethermind_version = 'unknown'
    nethermind_location = 'unknown'

    try:
        process_result = subprocess.run([
            'nethermind', '--version'
            ], capture_output=True, text=True)
        nethermind_found = True

        process_output = process_result.stdout
        result = re.search(r'Version: (?P<version>[^-\+]+)', process_output)
        if result:
            nethermind_version = result.group('version').strip()
        
        process_result = subprocess.run([
            'whereis', 'nethermind'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'nethermind: (\S+)', process_output)
        if result:
            nethermind_location = result.group(1).strip()

        nethermind_package_installed = False
        try:
            nethermind_package_installed = is_package_installed('nethermind')
        except Exception:
            return False

        if nethermind_package_installed:
            # Nethermind package is installed
            process_result = subprocess.run([
                'apt', 'show', 'nethermind'
                ], capture_output=True, text=True)
            
            process_output = process_result.stdout
            result = re.search(r'APT-Sources: (.*?)\n', process_output)
            if result:
                apt_sources = result.group(1).strip()
                apt_sources_splits = apt_sources.split(' ')
                if apt_sources_splits[0] == NETHERMIND_APT_SOURCE_URL:
                    installed_from_ppa = True

    except FileNotFoundError:
        pass
    
    install_nethermind_binary = True

    if nethermind_found:
        result = button_dialog(
            title='Nethermind binary found',
            text=(
f'''
The Nethermind binary seems to have already been installed. Here are some
details found:

Version: {nethermind_version}
Location: {nethermind_location}
Installed from package: {nethermind_package_installed}
Installed from Nethermind PPA: {installed_from_ppa}

Do you want to skip installing the Nethermind binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_nethermind_binary = (result == 2)

    if install_nethermind_binary:
        # Install Nethermind from PPA
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

        subprocess.run([
            'add-apt-repository', '-y', 'ppa:nethermindeth/nethermind'])
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'nethermind'])
        
        # Get Nethermind version
        try:
            process_result = subprocess.run([
                'nethermind', '--version'
                ], capture_output=True, text=True)
            nethermind_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (?P<version>[^-\+]+)', process_output)
            if result:
                nethermind_version = result.group('version').strip()
        except FileNotFoundError:
            pass
    
    # Check if Nethermind user or directory already exists
    nethermind_datadir = Path('/var/lib/nethermind')
    if nethermind_datadir.is_dir():
        process_result = subprocess.run([
            'du', '-sh', nethermind_datadir
            ], capture_output=True, text=True)
        
        process_output = process_result.stdout
        nethermind_datadir_size = process_output.split('\t')[0]

        result = button_dialog(
            title='Nethermind data directory found',
            text=(
f'''
An existing Nethermind data directory has been found. Here are some
details found:

Location: {nethermind_datadir}
Size: {nethermind_datadir_size}

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
            shutil.rmtree(nethermind_datadir)

    nethermind_user_exists = False
    process_result = subprocess.run([
        'id', '-u', 'nethermind'
    ])
    nethermind_user_exists = (process_result.returncode == 0)

    # Setup Nethermind user and directory
    if not nethermind_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', 'nethermind'])
    subprocess.run([
        'mkdir', '-p', nethermind_datadir])
    subprocess.run([
        'chown', '-R', 'nethermind:nethermind', nethermind_datadir])

    addparams = []

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', nethermind_version)
    if result:
        cleaned_nethermind_version = parse_version(result.group(1).strip())
        target_nethermind_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][EXECUTION_CLIENT_NETHERMIND])
        
        if cleaned_nethermind_version >= target_nethermind_version:
            merge_ready = True
    
    if merge_ready:
        if not setup_jwt_token_file():
            log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
            )

            return False

        addparams.append(f'--JsonRpc.JwtSecretFile {LINUX_JWT_TOKEN_FILE_PATH}')
    
    # Setup Nethermind systemd service
    if ports['eth1'] != DEFAULT_NETHERMIND_PORT:
        addparams.append(f'--Network.P2PPort {ports["eth1"]}')
        addparams.append(f'--Network.DiscoveryPort {ports["eth1"]}')
    
    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' \\\n    ' + ' \\\n    '.join(addparams)

    with open('/etc/systemd/system/' + nethermind_service_name, 'w') as service_file:
        service_file.write(NETHERMIND_SERVICE_DEFINITION[network].format(addparams=addparams_string))
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', nethermind_service_name])
    subprocess.run([
        'systemctl', 'enable', nethermind_service_name])
    
    # Wait a little before checking for Nethermind syncing since it can be slow to start
    delay = 30
    log.info(f'We are giving Nethermind {delay} seconds to start before testing it.')
    time.sleep(delay)

    # Verify proper Nethermind service installation
    service_details = get_systemd_service_details(nethermind_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Nethermind service not running properly',
            text=(
f'''
The Nethermind service we just created seems to have issues. Here are
some details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the Nethermind service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see
the logs with:

$ sudo journalctl -ru {nethermind_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, type the following command:

$ sudo journalctl -ru {nethermind_service_name}
'''
        )

        return False

    # Verify Nethermind JSON-RPC response
    local_nethermind_jsonrpc_url = 'http://127.0.0.1:8545'
    request_json = {
        'jsonrpc': '2.0',
        'method': 'web3_clientVersion',
        'id': 67
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = httpx.post(local_nethermind_jsonrpc_url, json=request_json, headers=headers)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Nethermind',
            text=(
f'''
We could not connect to Nethermind HTTP-RPC server. Here are some details
for this last test we tried to perform:

URL: {local_nethermind_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the Nethermind HTTP-RPC server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {nethermind_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, type the following command:

$ sudo journalctl -ru {nethermind_service_name}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Nethermind',
            text=(
f'''
We could not connect to Nethermind HTTP-RPC server. Here are some details
for this last test we tried to perform:

URL: {local_nethermind_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

We cannot proceed if the Nethermind HTTP-RPC server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {nethermind_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, type the following command:

$ sudo journalctl -ru {nethermind_service_name}
'''
        )

        return False
    
    # Verify proper Nethermind syncing
    def verifying_callback(set_percentage, log_text, change_status, set_result, get_exited):
        exe_is_healthy = False
        exe_has_few_peers = False
        exe_connected_peers = 0
        exe_starting_block = UNKNOWN_VALUE
        exe_current_block = UNKNOWN_VALUE
        exe_highest_block = UNKNOWN_VALUE
        exe_health_description = UNKNOWN_VALUE

        set_result({
            'exe_is_healthy': exe_is_healthy,
            'exe_starting_block': exe_starting_block,
            'exe_current_block': exe_current_block,
            'exe_highest_block': exe_highest_block,
            'exe_connected_peers': exe_connected_peers,
            'exe_health_description': exe_health_description
        })

        set_percentage(10)

        journalctl_cursor = None

        while True:

            if get_exited():
                return {
                    'exe_is_healthy': exe_is_healthy,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers,
                    'exe_health_description': exe_health_description
                }

            # Output logs
            command = []
            first_display = True
            if journalctl_cursor is None:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q', '-n', '25',
                    '-o', 'cat', '-u', nethermind_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '-o', 'cat', '--after-cursor=' + journalctl_cursor, '-u', nethermind_service_name]
                first_display = False

            process_result = subprocess.run(command, capture_output=True, text=True)

            process_output = ''
            if process_result.returncode == 0:
                process_output = process_result.stdout
            else:
                log_text(f'Return code: {process_result.returncode} while calling journalctl.')

            # Parse journalctl cursor and remove it from process_output
            log_length = len(process_output)
            if log_length > 0:
                result = re.search(r'-- cursor: (?P<cursor>[^\n]+)', process_output)
                if result:
                    journalctl_cursor = result.group('cursor')
                    process_output = (
                        process_output[:result.start()] +
                        process_output[result.end():])
                    process_output = process_output.rstrip()
            
                    log_length = len(process_output)

            if log_length > 0:
                if not first_display and process_output[0] != '\n':
                    process_output = '\n' + process_output
                log_text(process_output)

            time.sleep(1)
            
            local_nethermind_jsonrpc_url = 'http://127.0.0.1:8545'
            request_json = {
                'jsonrpc': '2.0',
                'method': 'eth_syncing',
                'id': 1
            }
            headers = {
                'Content-Type': 'application/json'
            }
            try:
                response = httpx.post(local_nethermind_jsonrpc_url, json=request_json,
                    headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nethermind.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Nethermind.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            local_nethermind_jsonrpc_url = 'http://127.0.0.1:8545'
            request_json = {
                'jsonrpc': '2.0',
                'method': 'net_peerCount',
                'id': 1
            }
            headers = {
                'Content-Type': 'application/json'
            }
            try:
                response = httpx.post(local_nethermind_jsonrpc_url, json=request_json,
                    headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nethermind.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Nethermind.')
                continue

            response_json = response.json()
            peer_count_json = response_json

            exe_starting_block = UNKNOWN_VALUE
            exe_current_block = UNKNOWN_VALUE
            exe_highest_block = UNKNOWN_VALUE
            if (
                syncing_json and
                'result' in syncing_json and
                syncing_json['result']
                ):
                if 'startingBlock' in syncing_json['result']:
                    exe_starting_block = int(syncing_json['result']['startingBlock'], 16)
                if 'currentBlock' in syncing_json['result']:
                    exe_current_block = int(syncing_json['result']['currentBlock'], 16)
                if 'highestBlock' in syncing_json['result']:
                    exe_highest_block = int(syncing_json['result']['highestBlock'], 16)

            exe_connected_peers = 0
            if (
                peer_count_json and
                'result' in peer_count_json and
                peer_count_json['result']
                ):
                exe_connected_peers = int(peer_count_json['result'], 16)
            
            exe_has_few_peers = exe_connected_peers >= EXE_MIN_FEW_PEERS

            exe_is_healthy = False
            exe_health_description = UNKNOWN_VALUE

            # Query health endpoint

            local_nethermind_health_url = 'http://127.0.0.1:8545/health'

            try:
                response = httpx.post(local_nethermind_health_url)
                if response.status_code != 200:
                    log_text(
                        f'Status code: {response.status_code} while querying Nethermind Health.')
                else:
                    response_json = response.json()
                    health_json = response_json

                    if 'status' in health_json:
                        exe_is_healthy = (health_json['status'] == 'Healthy')
                    
                    if ('entries' in health_json and
                        'node-health' in health_json['entries'] and
                        'description' in health_json['entries']['node-health']):
                        exe_health_description = health_json['entries']['node-health']['description']

            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nethermind Health.')

            if exe_is_healthy or exe_has_few_peers:
                set_percentage(100)
            else:
                set_percentage(10 +
                    round(min(exe_connected_peers / EXE_MIN_FEW_PEERS, 1.0) * 90.0))

            formatted_description = (
'''
Healthy: Unknown
Connected Peers: Unknown
'''
        ).strip()

            if exe_health_description != UNKNOWN_VALUE:
                formatted_description = format_for_terminal(exe_health_description)

            change_status(formatted_description)

            if exe_is_healthy or exe_has_few_peers:
                return {
                    'exe_is_healthy': exe_is_healthy,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers,
                    'exe_health_description': exe_health_description
                }
            else:
                set_result({
                    'exe_is_healthy': exe_is_healthy,
                    'exe_starting_block': exe_starting_block,
                    'exe_current_block': exe_current_block,
                    'exe_highest_block': exe_highest_block,
                    'exe_connected_peers': exe_connected_peers,
                    'exe_health_description': exe_health_description
                })

    result = progress_log_dialog(
        title='Verifying proper Nethermind service installation',
        text=(
f'''
We are waiting for Nethermind to become healthy or find enough peers to
confirm that it is working properly.
'''     ),
        status_text=(
'''
Healthy: Unknown
Connected Peers: Unknown
'''
        ).strip(),
        with_skip=True,
        run_callback=verifying_callback
    ).run()
    
    if not result:
        log.warning('Nethermind verification was cancelled.')
        return False

    if result.get('skipping', False):
        log.warning('Skipping Nethermind verification.')
        return True

    health_description = result['exe_health_description']
    if health_description != UNKNOWN_VALUE:
        health_description = format_for_terminal(health_description)
    else:
        health_description = (
f'''
Healthy: Unknown
Connected Peers: {result['exe_connected_peers']}
'''
        ).strip()

    exe_has_few_peers = (result['exe_connected_peers'] >= EXE_MIN_FEW_PEERS)

    if not result['exe_is_healthy'] and not exe_has_few_peers:
        # We could not get a proper result from Nethermind
        result = button_dialog(
            title='Nethermind verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the Nethermind
installation. Here are some results for the last tests we performed:

{health_description}

We cannot proceed if Nethermind is not installed properly. Make sure to
check the logs and fix any issue found there. You can see the logs with:

$ sudo journalctl -ru {nethermind_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, type the following command:

$ sudo journalctl -ru {nethermind_service_name}
'''
        )

        return False

    log.info(
f'''
Nethermind is installed and working properly.

{health_description}
''' )
    time.sleep(5)

    return True

def detect_merge_ready(network):
    is_merge_ready = True

    # All networks are merge ready now.

    return {'result': is_merge_ready}

def install_lighthouse(network, eth1_fallbacks, consensus_checkpoint_url, ports,
    mevboost_installed):
    # Install Lighthouse for the selected network

    # Check for existing systemd service
    lighthouse_bn_service_exists = False
    lighthouse_bn_service_name = LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME

    service_details = get_systemd_service_details(lighthouse_bn_service_name)

    if service_details['LoadState'] == 'loaded':
        lighthouse_bn_service_exists = True
    
    if lighthouse_bn_service_exists:
        result = button_dialog(
            title='Lighthouse beacon node service found',
            text=(
f'''
The lighthouse beacon node service seems to have already been created. Here
are some details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to skip installing lighthouse and its beacon node service?
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
            'systemctl', 'stop', lighthouse_bn_service_name])

    result = button_dialog(
        title='Lighthouse installation',
        text=(
'''
This next step will install Lighthouse, an Ethereum consensus client that
includes a beacon node and a validator client in the same binary.

It will download the official binary from GitHub, verify its PGP signature
and extract it for easy use.

Once installed locally, it will create a systemd service that will
automatically start the Lighthouse beacon node on reboot or if it crashes.
The beacon node will be started and you will slowly start syncing with the
Ethereum network. This syncing process can take a few hours or days even
with good hardware and good internet if you did not select a working
checkpoint sync endpoint.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if lighthouse is already installed
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
            log.warning('CPU does not support ADX instructions. '
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
        
        # Extracting the Lighthouse binary archive
        subprocess.run([
            'tar', 'xvf', binary_path, '--directory', LIGHTHOUSE_INSTALLED_DIRECTORY])
        
        # Remove download leftovers
        binary_path.unlink()
        signature_path.unlink()

        # Get Lighthouse version
        try:
            process_result = subprocess.run([
                'lighthouse', '--version'
                ], capture_output=True, text=True)
            lighthouse_found = True

            process_output = process_result.stdout
            result = re.search(r'Lighthouse (.*?)\n', process_output)
            if result:
                lighthouse_version = result.group(1).strip()
        except FileNotFoundError:
            pass

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

    addparams = []

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', lighthouse_version)
    if result:
        cleaned_lighthouse_version = parse_version(result.group(1).strip())
        target_lighthouse_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_LIGHTHOUSE])

        if cleaned_lighthouse_version >= target_lighthouse_version:
            merge_ready = True

    if merge_ready:
        if not setup_jwt_token_file():
            log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
            )

            return False

        addparams.append(f'--execution-jwt {LINUX_JWT_TOKEN_FILE_PATH}')

    # Setup Lighthouse beacon node systemd service
    service_definition = LIGHTHOUSE_BN_SERVICE_DEFINITION[network]

    local_eth1_endpoint = 'http://127.0.0.1:8545'
    eth1_endpoints_flag = '--eth1-endpoints'
    if merge_ready:
        local_eth1_endpoint = 'http://127.0.0.1:8551'
        eth1_endpoints_flag = '--execution-endpoint'
    
    eth1_endpoints = [local_eth1_endpoint] + eth1_fallbacks
    eth1_endpoints_string = ','.join(eth1_endpoints)

    addparams.append(f'{eth1_endpoints_flag} {eth1_endpoints_string}')

    if ports['eth2_bn'] != DEFAULT_LIGHTHOUSE_BN_PORT:
        addparams.append(f'--port {ports["eth2_bn"]}')
    
    if consensus_checkpoint_url != '':
        addparams.append(f'--checkpoint-sync-url "{consensus_checkpoint_url}"')

    if mevboost_installed:
        addparams.append(f'--builder http://127.0.0.1:18550')

    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' ' + ' '.join(addparams)

    service_definition = service_definition.format(addparams=addparams_string)

    with open('/etc/systemd/system/' + lighthouse_bn_service_name, 'w') as service_file:
        service_file.write(service_definition)
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', lighthouse_bn_service_name])
    subprocess.run([
        'systemctl', 'enable', lighthouse_bn_service_name])
    
    delay = 45
    log.info(
f'''
We are giving the lighthouse beacon node {delay} seconds to start before
testing it.

You might see some error and warn messages about your eth1 node not being in
sync, being far behind or about the beacon node being unable to connect to any
eth1 node. Those message are normal to see while your Ethereum execution
client is syncing.
'''
    )
    time.sleep(delay)

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

        log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    # Verify proper Lighthouse beacon node installation and syncing
    keep_retrying = True

    retry_index = 0
    retry_count = 10
    retry_delay = 30
    retry_delay_increase = 15
    last_exception = None
    last_status_code = None

    local_lighthouse_bn_http_base = 'http://127.0.0.1:5052'
    
    lighthouse_bn_version_query = BN_VERSION_EP
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_version_query
    headers = {
        'accept': 'application/json'
    }

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(lighthouse_bn_query_url, headers=headers)
        except httpx.RequestError as exception:
            last_exception = exception

            log.error(f'Exception {exception} when trying to connect to the beacon node on '
                f'{lighthouse_bn_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        if response.status_code != 200:
            last_status_code = response.status_code

            log.error(f'Error code {response.status_code} when trying to connect to the beacon '
                f'node on {lighthouse_bn_query_url}')
            
            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        keep_retrying = False
        last_exception = None
        last_status_code = None
    
    if keep_retrying:
        if last_exception is not None:
            result = button_dialog(
                title='Cannot connect to Lighthouse beacon node',
                text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Exception: {last_exception}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot connect to Lighthouse beacon node',
                text=(
f'''
We could not connect to lighthouse beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Status code: {last_status_code}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )
        
        return False

    # Verify proper Lighthouse beacon node syncing
    def verifying_callback(set_percentage, log_text, change_status, set_result, get_exited):
        bn_is_working = False
        bn_is_syncing = False
        bn_has_few_peers = False
        bn_connected_peers = 0
        bn_head_slot = UNKNOWN_VALUE
        bn_sync_distance = UNKNOWN_VALUE

        set_result({
            'bn_is_working': bn_is_working,
            'bn_is_syncing': bn_is_syncing,
            'bn_head_slot': bn_head_slot,
            'bn_sync_distance': bn_sync_distance,
            'bn_connected_peers': bn_connected_peers
        })

        set_percentage(10)

        journalctl_cursor = None

        while True:

            if get_exited():
                return {
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                }

            # Output logs
            command = []
            first_display = True
            if journalctl_cursor is None:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q', '-n', '25',
                    '-o', 'cat', '-u', lighthouse_bn_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '-o', 'cat', '--after-cursor=' + journalctl_cursor, '-u',
                    lighthouse_bn_service_name]
                first_display = False

            process_result = subprocess.run(command, capture_output=True, text=True)

            process_output = ''
            if process_result.returncode == 0:
                process_output = process_result.stdout
            else:
                log_text(f'Return code: {process_result.returncode} while calling journalctl.')

            # Parse journalctl cursor and remove it from process_output
            log_length = len(process_output)
            if log_length > 0:
                result = re.search(r'-- cursor: (?P<cursor>[^\n]+)', process_output)
                if result:
                    journalctl_cursor = result.group('cursor')
                    process_output = (
                        process_output[:result.start()] +
                        process_output[result.end():])
                    process_output = process_output.rstrip()
            
                    log_length = len(process_output)

            if log_length > 0:
                if not first_display and process_output[0] != '\n':
                    process_output = '\n' + process_output
                log_text(process_output)

            time.sleep(1)
            
            lighthouse_bn_syncing_query = BN_SYNCING_EP
            lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_syncing_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(lighthouse_bn_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Lighthouse beacon node.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Lighthouse beacon node.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            lighthouse_bn_peer_count_query = BN_PEER_COUNT_EP
            lighthouse_bn_query_url = (
                local_lighthouse_bn_http_base + lighthouse_bn_peer_count_query)
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(lighthouse_bn_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Lighthouse beacon node.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Lighthouse beacon node.')
                continue

            response_json = response.json()
            peer_count_json = response_json

            if (
                syncing_json and
                'data' in syncing_json and
                'is_syncing' in syncing_json['data']
                ):
                bn_is_syncing = bool(syncing_json['data']['is_syncing'])
            else:
                bn_is_syncing = False
            
            if (
                syncing_json and
                'data' in syncing_json and
                'head_slot' in syncing_json['data']
                ):
                bn_head_slot = syncing_json['data']['head_slot']
            else:
                bn_head_slot = UNKNOWN_VALUE

            if (
                syncing_json and
                'data' in syncing_json and
                'sync_distance' in syncing_json['data']
                ):
                bn_sync_distance = syncing_json['data']['sync_distance']
            else:
                bn_sync_distance = UNKNOWN_VALUE

            bn_connected_peers = 0
            if (
                peer_count_json and
                'data' in peer_count_json and
                'connected' in peer_count_json['data']
                ):
                bn_connected_peers = int(peer_count_json['data']['connected'])
            
            bn_has_few_peers = bn_connected_peers >= BN_MIN_FEW_PEERS

            if bn_is_syncing or bn_has_few_peers:
                set_percentage(100)
            else:
                set_percentage(10 + round(min(bn_connected_peers / BN_MIN_FEW_PEERS, 1.0) * 90.0))

            change_status((
f'''
Syncing: {bn_is_syncing} (Head slot: {bn_head_slot}, Sync distance: {bn_sync_distance})
Connected Peers: {bn_connected_peers}
'''         ).strip())

            if bn_is_syncing or bn_has_few_peers:
                bn_is_working = True
                return {
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                }
            else:
                set_result({
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                })

    result = progress_log_dialog(
        title='Verifying proper Lighthouse beacon node service installation',
        text=(
f'''
We are waiting for Lighthouse beacon node to sync or find enough peers to
confirm that it is working properly.
'''     ),
        status_text=(
'''
Syncing: Unknown (Head slot: Unknown, Sync distance: Unknown)
Connected Peers: Unknown
'''
        ).strip(),
        run_callback=verifying_callback
    ).run()
    
    if not result:
        log.warning('Lighthouse beacon node verification was cancelled.')
        return False

    if not result['bn_is_working']:
        # We could not get a proper result from Lighthouse beacon node
        result = button_dialog(
            title='Lighthouse beacon node verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the lighthouse beacon node
installation. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

We cannot proceed if the lighthouse beacon node is not installed properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    log.info(
f'''
The lighthouse beacon node is installed and working properly.

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}
''' )
    time.sleep(5)

    return True

def install_nimbus(network, eth1_fallbacks, consensus_checkpoint_url, ports,
    mevboost_installed):
    # Install Nimbus for the selected network

    # Check for existing systemd service
    nimbus_service_exists = False
    nimbus_service_name = NIMBUS_SYSTEMD_SERVICE_NAME

    service_details = get_systemd_service_details(nimbus_service_name)

    if service_details['LoadState'] == 'loaded':
        nimbus_service_exists = True
    
    if nimbus_service_exists:
        result = button_dialog(
            title='Nimbus service found',
            text=(
f'''
The Nimbus service seems to have already been created. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to skip installing Nimbus and its beacon node service?
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
        
        # User wants to proceed, make sure the Nimbus beacon node service is stopped first
        subprocess.run([
            'systemctl', 'stop', nimbus_service_name])

    result = button_dialog(
        title='Nimbus installation',
        text=(
'''
This next step will install Nimbus, an Ethereum consensus client that
includes a beacon node and a validator client in the same process.

It will download the official binary from GitHub and extract it for easy
use.

Once installed locally, it will create a systemd service that will
automatically start the Nimbus on reboot or if it crashes. The client
will be started and you will slowly start syncing with the Ethereum
network. This syncing process can take a few hours or days even with good
hardware and good internet.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if Nimbus is already installed
    nimbus_found = False
    nimbus_version = 'unknown'
    nimbus_location = 'unknown'

    try:
        process_result = subprocess.run([
            'nimbus_beacon_node', '--version'
            ], capture_output=True, text=True)
        nimbus_found = True

        process_output = process_result.stdout
        result = re.search(r'Nimbus beacon node v?(?P<version>[^-]+)', process_output)
        if result:
            nimbus_version = result.group('version').strip()
        
        process_result = subprocess.run([
            'whereis', 'nimbus_beacon_node'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'nimbus_beacon_node: (.*?)\n', process_output)
        if result:
            nimbus_location = result.group(1).strip()

    except FileNotFoundError:
        pass
    
    install_nimbus_binary = True

    if nimbus_found:
        result = button_dialog(
            title='Nimbus binary found',
            text=(
f'''
The Nimbus binary seems to have already been installed. Here are some
details found:

Version: {nimbus_version}
Location: {nimbus_location}

Do you want to skip installing the Nimbus binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_nimbus_binary = (result == 2)
    
    if install_nimbus_binary:
        # Getting latest Nimbus release files
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

        archive_filename_comp = 'nimbus-eth2_Linux_amd64'

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
        download_path = Path(Path.home(), 'ethwizard', 'downloads')
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
                if entry.name.startswith('.'):
                    continue

                if entry.is_dir():
                    if entry.name == 'build':
                        build_path = entry.path
                    else:
                        build_path = os.path.join(entry.path, 'build')
                    break
        
        if build_path is None:
            log.error('Cannot find the correct directory in the extracted Nimbus archive.')
            return False

        src_nimbus_bn_path = Path(build_path, 'nimbus_beacon_node')
        src_nimbus_vc_path = Path(build_path, 'nimbus_validator_client')

        if not src_nimbus_bn_path.is_file() or not src_nimbus_vc_path.is_file():
            log.error(f'Cannot find the Nimbus binaries in the extracted archive.')
            return False
        
        subprocess.run(['cp', src_nimbus_bn_path, NIMBUS_INSTALLED_DIRECTORY])
        subprocess.run(['cp', src_nimbus_vc_path, NIMBUS_INSTALLED_DIRECTORY])

        # Remove extraction leftovers
        shutil.rmtree(extract_directory)

        # Get Nimbus version
        try:
            process_result = subprocess.run([
                'nimbus_beacon_node', '--version'
                ], capture_output=True, text=True)
            nimbus_found = True

            process_output = process_result.stdout
            result = re.search(r'Nimbus beacon node v?(?P<version>[^-]+)', process_output)
            if result:
                nimbus_version = result.group('version').strip()
        except FileNotFoundError:
            pass

    # Check if Nimbus user or directory already exists
    nimbus_datadir = Path('/var/lib/nimbus')
    if nimbus_datadir.exists() and nimbus_datadir.is_dir():
        process_result = subprocess.run([
            'du', '-sh', nimbus_datadir
            ], capture_output=True, text=True)
        
        process_output = process_result.stdout
        nimbus_datadir_size = process_output.split('\t')[0]

        result = button_dialog(
            title='Nimbus data directory found',
            text=(
f'''
An existing Nimbus data directory has been found. Here are some details
found:

Location: {nimbus_datadir}
Size: {nimbus_datadir_size}

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
            shutil.rmtree(nimbus_datadir)

    nimbus_user_exists = False
    nimbus_username = 'nimbus'
    process_result = subprocess.run([
        'id', '-u', nimbus_username
    ])
    nimbus_user_exists = (process_result.returncode == 0)

    # Setup Lighthouse beacon node user and directory
    if not nimbus_user_exists:
        subprocess.run([
            'useradd', '--no-create-home', '--shell', '/bin/false', nimbus_username])
    subprocess.run([
        'mkdir', '-p', nimbus_datadir])
    subprocess.run([
        'chown', '-R', f'{nimbus_username}:{nimbus_username}', nimbus_datadir])
    subprocess.run([
        'chmod', '700', nimbus_datadir])

    addparams = []

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', nimbus_version)
    if result:
        cleaned_nimbus_version = parse_version(result.group(1).strip())
        target_nimbus_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_NIMBUS])

        if cleaned_nimbus_version >= target_nimbus_version:
            merge_ready = True

    if merge_ready:
        if not setup_jwt_token_file():
            log.error(
f'''
Unable to create JWT token file in {LINUX_JWT_TOKEN_FILE_PATH}
'''
            )

            return False

        addparams.append(f'--jwt-secret={LINUX_JWT_TOKEN_FILE_PATH}')

    # Setup Nimbus systemd service
    service_definition = NIMBUS_SERVICE_DEFINITION[network]

    local_eth1_endpoint = 'http://127.0.0.1:8545'
    eth1_endpoints_flag = '--web3-url='
    if merge_ready:
        local_eth1_endpoint = 'http://127.0.0.1:8551'

    addparams.append(f'{eth1_endpoints_flag}{local_eth1_endpoint}')

    if ports['eth2_bn'] != DEFAULT_NIMBUS_BN_PORT:
        addparams.append(f'--tcp-port={ports["eth2_bn"]}')
        addparams.append(f'--udp-port={ports["eth2_bn"]}')
    
    if consensus_checkpoint_url != '':
        # Perform checkpoint sync with the trustedNodeSync command
        log.info('Initializing Nimbus with a checkpoint sync endpoint.')
        process_result = subprocess.run([
            'sudo', '-u', nimbus_username, '-g', nimbus_username, NIMBUS_INSTALLED_PATH,
            'trustedNodeSync',
            f'--network={network}',
            f'--data-dir={nimbus_datadir}',
            f'--trusted-node-url={consensus_checkpoint_url}',
            '--backfill=false'
        ])
        if process_result.returncode != 0:
            log.error('Unable to initialize Nimbus with a checkpoint sync endpoint.')
            return False

    if mevboost_installed:
        addparams.append('--payload-builder=true')
        addparams.append('--payload-builder-url=http://127.0.0.1:18550')

    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' \\\n    ' + ' \\\n    '.join(addparams)

    service_definition = service_definition.format(addparams=addparams_string)

    with open('/etc/systemd/system/' + nimbus_service_name, 'w') as service_file:
        service_file.write(service_definition)
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', nimbus_service_name])
    subprocess.run([
        'systemctl', 'enable', nimbus_service_name])
    
    delay = 30
    log.info(
f'''
We are giving Nimbus {delay} seconds to start before testing it.
'''
    )
    time.sleep(delay)

    # Check if the Lighthouse beacon node service is still running
    service_details = get_systemd_service_details(nimbus_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Nimbus service not running properly',
            text=(
f'''
The Nimbus service we just created seems to have issues.
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

$ sudo journalctl -ru {nimbus_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {nimbus_service_name}
'''
        )

        return False

    # Verify proper Nimbus beacon node installation and syncing
    keep_retrying = True

    retry_index = 0
    retry_count = 10
    retry_delay = 30
    retry_delay_increase = 15
    last_exception = None
    last_status_code = None

    local_bn_http_base = 'http://127.0.0.1:5052'
    
    bn_version_query = BN_VERSION_EP
    bn_query_url = local_bn_http_base + bn_version_query
    headers = {
        'accept': 'application/json'
    }

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(bn_query_url, headers=headers)
        except httpx.RequestError as exception:
            last_exception = exception

            log.error(f'Exception {exception} when trying to connect to the beacon node on '
                f'{bn_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        if response.status_code != 200:
            last_status_code = response.status_code

            log.error(f'Error code {response.status_code} when trying to connect to the beacon '
                f'node on {bn_query_url}')
            
            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        keep_retrying = False
        last_exception = None
        last_status_code = None
    
    if keep_retrying:
        if last_exception is not None:
            result = button_dialog(
                title='Cannot connect to Nimbus beacon node',
                text=(
f'''
We could not connect to Nimbus beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {bn_query_url}
Method: GET
Headers: {headers}
Exception: {last_exception}

We cannot proceed if the Nimbus beacon node HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {nimbus_service_name}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Nimbus service logs, type the following command:

$ sudo journalctl -ru {nimbus_service_name}
'''
            )
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot connect to Nimbus beacon node',
                text=(
f'''
We could not connect to Nimbus beacon node HTTP server. Here are some
details for this last test we tried to perform:

URL: {bn_query_url}
Method: GET
Headers: {headers}
Status code: {last_status_code}

We cannot proceed if the Nimbus beacon node HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {nimbus_service_name}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Nimbus service logs, type the following command:

$ sudo journalctl -ru {nimbus_service_name}
'''
            )
        
        return False

    # Verify proper Nimbus beacon node syncing
    def verifying_callback(set_percentage, log_text, change_status, set_result, get_exited):
        bn_is_working = False
        bn_is_syncing = False
        bn_has_few_peers = False
        bn_connected_peers = 0
        bn_head_slot = UNKNOWN_VALUE
        bn_sync_distance = UNKNOWN_VALUE

        set_result({
            'bn_is_working': bn_is_working,
            'bn_is_syncing': bn_is_syncing,
            'bn_head_slot': bn_head_slot,
            'bn_sync_distance': bn_sync_distance,
            'bn_connected_peers': bn_connected_peers
        })

        set_percentage(10)

        journalctl_cursor = None

        while True:

            if get_exited():
                return {
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                }

            # Output logs
            command = []
            first_display = True
            if journalctl_cursor is None:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q', '-n', '25',
                    '-o', 'cat', '-u', nimbus_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '-o', 'cat', '--after-cursor=' + journalctl_cursor, '-u',
                    nimbus_service_name]
                first_display = False

            process_result = subprocess.run(command, capture_output=True, text=True)

            process_output = ''
            if process_result.returncode == 0:
                process_output = process_result.stdout
            else:
                log_text(f'Return code: {process_result.returncode} while calling journalctl.')

            # Parse journalctl cursor and remove it from process_output
            log_length = len(process_output)
            if log_length > 0:
                result = re.search(r'-- cursor: (?P<cursor>[^\n]+)', process_output)
                if result:
                    journalctl_cursor = result.group('cursor')
                    process_output = (
                        process_output[:result.start()] +
                        process_output[result.end():])
                    process_output = process_output.rstrip()
            
                    log_length = len(process_output)

            if log_length > 0:
                if not first_display and process_output[0] != '\n':
                    process_output = '\n' + process_output
                log_text(process_output)

            time.sleep(1)
            
            bn_syncing_query = BN_SYNCING_EP
            bn_query_url = local_bn_http_base + bn_syncing_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(bn_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nimbus beacon node.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Nimbus beacon node.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            bn_peer_count_query = BN_PEER_COUNT_EP
            bn_query_url = (
                local_bn_http_base + bn_peer_count_query)
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(bn_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nimbus beacon node.')
                continue

            if response.status_code != 200:
                log_text(
                    f'Status code: {response.status_code} while querying Nimbus beacon node.')
                continue

            response_json = response.json()
            peer_count_json = response_json

            if (
                syncing_json and
                'data' in syncing_json and
                'is_syncing' in syncing_json['data']
                ):
                bn_is_syncing = bool(syncing_json['data']['is_syncing'])
            else:
                bn_is_syncing = False
            
            if (
                syncing_json and
                'data' in syncing_json and
                'head_slot' in syncing_json['data']
                ):
                bn_head_slot = syncing_json['data']['head_slot']
            else:
                bn_head_slot = UNKNOWN_VALUE

            if (
                syncing_json and
                'data' in syncing_json and
                'sync_distance' in syncing_json['data']
                ):
                bn_sync_distance = syncing_json['data']['sync_distance']
            else:
                bn_sync_distance = UNKNOWN_VALUE

            bn_connected_peers = 0
            if (
                peer_count_json and
                'data' in peer_count_json and
                'connected' in peer_count_json['data']
                ):
                bn_connected_peers = int(peer_count_json['data']['connected'])
            
            bn_has_few_peers = bn_connected_peers >= BN_MIN_FEW_PEERS

            if bn_is_syncing or bn_has_few_peers:
                set_percentage(100)
            else:
                set_percentage(10 + round(min(bn_connected_peers / BN_MIN_FEW_PEERS, 1.0) * 90.0))

            change_status((
f'''
Syncing: {bn_is_syncing} (Head slot: {bn_head_slot}, Sync distance: {bn_sync_distance})
Connected Peers: {bn_connected_peers}
'''         ).strip())

            if bn_is_syncing or bn_has_few_peers:
                bn_is_working = True
                return {
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                }
            else:
                set_result({
                    'bn_is_working': bn_is_working,
                    'bn_is_syncing': bn_is_syncing,
                    'bn_head_slot': bn_head_slot,
                    'bn_sync_distance': bn_sync_distance,
                    'bn_connected_peers': bn_connected_peers
                })

    result = progress_log_dialog(
        title='Verifying proper Nimbus service installation',
        text=(
f'''
We are waiting for Nimbus beacon node to sync or find enough peers to
confirm that it is working properly.
'''     ),
        status_text=(
'''
Syncing: Unknown (Head slot: Unknown, Sync distance: Unknown)
Connected Peers: Unknown
'''
        ).strip(),
        run_callback=verifying_callback
    ).run()
    
    if not result:
        log.warning('Nimbus beacon node verification was cancelled.')
        return False

    if not result['bn_is_working']:
        # We could not get a proper result from Nimbus beacon node
        result = button_dialog(
            title='Nimbus beacon node verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the Nimbus beacon node
installation. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

We cannot proceed if the Nimbus beacon node is not installed properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {nimbus_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nimbus service logs, type the following command:

$ sudo journalctl -ru {nimbus_service_name}
'''
        )

        return False
    
    log.info(
f'''
Nimbus is installed and working properly.

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}
''' )
    time.sleep(5)

    return True

def obtain_keys(network, consensus_client):
    # Obtain validator keys for the selected network

    staking_deposit_cli_path = Path(Path.home(), 'ethwizard', 'staking-deposit-cli')
    validator_keys_path = Path(staking_deposit_cli_path, 'validator_keys')

    # Check if there are keys already imported in our consensus client

    public_keys = []
    keys_location = UNKNOWN_VALUE

    if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        # Check if there are keys already imported in Lighthouse validator client

        lighthouse_datadir = Path('/var/lib/lighthouse')
        keys_location = lighthouse_datadir

        process_result = subprocess.run([
            LIGHTHOUSE_INSTALLED_PATH, '--network', network, 'account', 'validator', 'list',
            '--datadir', lighthouse_datadir
            ], capture_output=True, text=True)
        if process_result.returncode == 0:
            process_output = process_result.stdout
            public_keys = re.findall(r'0x[0-9a-f]{96}\s', process_output)
            public_keys = list(map(lambda x: x.strip(), public_keys))
    
    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

        # Check if there are keys already imported in Nimbus

        nimbus_datadir = Path('/var/lib/nimbus')
        keys_location = nimbus_datadir
        nimbus_validators_path = nimbus_datadir.joinpath('validators')

        with os.scandir(nimbus_validators_path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue

                if entry.is_dir():
                    result = re.search(r'0x[0-9a-f]{96}', entry.name)
                    if result:
                        public_keys.append(result.group(0))
        
    if len(public_keys) > 0:
        # We already have keys imported

        result = button_dialog(
            title='Validator keys already imported',
            text=(
f'''
It seems like validator keys have already been imported. Here are some
details found:

Number of validators: {len(public_keys)}
Location: {keys_location}

Do you want to skip generating new keys?
'''             ),
            buttons=[
                ('Skip', 1),
                ('Generate', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            generated_keys = search_for_generated_keys(validator_keys_path)
            return generated_keys

        # We want to obtain new keys from here
    
    # Check if there are keys already created
    generated_keys = search_for_generated_keys(validator_keys_path)
    if (
        generated_keys['deposit_data_path'] is not None or
        len(generated_keys['keystore_paths']) > 0
    ):
        result = button_dialog(
            title='Validator keys already created',
            text=(
f'''
It seems like validator keys have already been created. Here are some
details found:

Number of keystores: {len(generated_keys['keystore_paths'])}
Deposit data file: {generated_keys['deposit_data_path']}
Location: {validator_keys_path}

If there is no keystore, it's probably because they were already imported
into the validator client.

Do you want to skip generating new keys? Generating new keys will destroy
all previously generated keys and deposit data file.
'''         ),
            buttons=[
                ('Skip', 1),
                ('Generate', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return generated_keys

    currency = NETWORK_CURRENCY[network]

    result = button_dialog(
        title='CAUTION',
        text=(HTML(
f'''
<style bg="red" fg="black">If the <b>mnemonic</b> you are about to create is lost or stolen, you will also
lose your funds.</style>
'''     )),
        buttons=[
            ('Understood', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    obtained_keys = False
    actual_keys = None

    while not obtained_keys:

        result = button_dialog(
            title='Importing or generating keys',
            text=(
f'''
This next step will import your keys if you already generated them
elsewhere or help you generate the keys needed to be a validator.

It is recommended to generate your keys offline using the official
staking-deposit-cli tool or Wagyu Key Gen. You can download these tools
from:

- https://github.com/ethereum/staking-deposit-cli
- https://github.com/stake-house/wagyu-key-gen

You can put that binary on a USB drive, generate your keys on a different
machine that is not connected to the internet, copy your keys on the USB
drive and import them here.

An easier but somewhat riskier alternative is let this wizard download
the tool and generate your keys on this machine.

Would you like to import your keys or generate them here?
'''         ),
            buttons=[
                ('Import', 1),
                ('Generate', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            # Import keys from a selected directory

            selected_keys_directory = select_keys_directory(network)
            if type(selected_keys_directory) is not str and not selected_keys_directory:
                return False
            
            if selected_keys_directory == '':
                continue

            # Clean potential leftover keys
            if validator_keys_path.is_dir():
                shutil.rmtree(validator_keys_path)
            validator_keys_path.mkdir(parents=True, exist_ok=True)

            # Copy keys into validator_keys_path
            with os.scandir(selected_keys_directory) as it:
                for entry in it:
                    if entry.name.startswith('.'):
                        continue
                    
                    if not entry.is_file():
                        continue

                    if not entry.name.endswith('.json'):
                        continue

                    if not (
                        entry.name.startswith('deposit_data') or
                        entry.name.startswith('keystore')):
                        continue

                    target_path = validator_keys_path.joinpath(entry.name)
                    os.rename(entry.path, target_path)

            # Verify the generated keys
            imported_keys = search_for_generated_keys(validator_keys_path)
            
            if len(imported_keys['keystore_paths']) == 0:
                log.warning(f'No key has been found while importing them from {validator_keys_path}')
            else:
                actual_keys = imported_keys
                obtained_keys = True

            continue

        result = button_dialog(
            title='Generating keys',
            text=(HTML(
f'''
This next step will generate the keys needed to be a validator on this
machine.

It will download the official staking-deposit-cli binary from GitHub,
verify its SHA256 checksum, extract it and start it.

The staking-deposit-cli tool is executed in an interactive way where you
have to answer a few questions. It will help you create a mnemonic from
which all your keys will be derived from. The mnemonic is the ultimate key.
It is <style bg="red" fg="black"><b>VERY IMPORTANT</b></style> to securely and privately store your mnemonic. It can
be used to recreate your validator keys and eventually withdraw your funds.

When asked how many validators you wish to run, remember that you will have
to do a 32 {currency} deposit for each validator.
'''         )),
            buttons=[
                ('Keep going', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
    
        # Check if staking-deposit-cli is already installed
        staking_deposit_cli_binary = Path(staking_deposit_cli_path, 'deposit')

        staking_deposit_cli_found = False

        if staking_deposit_cli_binary.exists() and staking_deposit_cli_binary.is_file():
            try:
                process_result = subprocess.run([
                    staking_deposit_cli_binary, '--help'
                    ], capture_output=True, text=True)
                staking_deposit_cli_found = True

                # TODO: Validate the output of deposit --help to make sure it's fine? Maybe?
                # process_output = process_result.stdout

            except FileNotFoundError:
                pass
        
        install_staking_deposit_binary = True

        if staking_deposit_cli_found:
            result = button_dialog(
                title='staking-deposit-cli binary found',
                text=(
f'''
The staking-deposit-cli binary seems to have already been installed. Here
are some details found:

Location: {staking_deposit_cli_binary}

Do you want to skip installing the staking-deposit-cli binary?
'''             ),
                buttons=[
                    ('Skip', 1),
                    ('Install', 2),
                    ('Quit', False)
                ]
            ).run()

            if not result:
                return result
        
            install_staking_deposit_binary = (result == 2)

        if install_staking_deposit_binary:
            # Getting latest staking-deposit-cli release files
            sdc_gh_release_url = GITHUB_REST_API_URL + SDC_LATEST_RELEASE
            headers = {'Accept': GITHUB_API_VERSION}
            try:
                response = httpx.get(sdc_gh_release_url, headers=headers,
                    follow_redirects=True)
            except httpx.RequestError as exception:
                log.error(f'Cannot get latest staking-deposit-cli release from Github. '
                    f'Exception {exception}')
                return False

            if response.status_code != 200:
                log.error(f'Cannot get latest staking-deposit-cli release from Github. '
                    f'Status code {response.status_code}')
                return False
            
            release_json = response.json()

            if 'assets' not in release_json:
                log.error('No assets in Github release for staking-deposit-cli.')
                return False
            
            binary_asset = None
            checksum_asset = None

            for asset in release_json['assets']:
                if 'name' not in asset:
                    continue
                if 'browser_download_url' not in asset:
                    continue
            
                file_name = asset['name']
                file_url = asset['browser_download_url']

                if file_name.endswith('linux-amd64.tar.gz'):
                    binary_asset = {
                        'file_name': file_name,
                        'file_url': file_url
                    }
                elif file_name.endswith('linux-amd64.sha256'):
                    checksum_asset = {
                        'file_name': file_name,
                        'file_url': file_url
                    }
            
            if binary_asset is None:
                log.error('No staking-deposit-cli binary found in Github release')
                return False
            
            checksum_path = None

            if checksum_asset is None:
                log.warning('No staking-deposit-cli checksum found in Github release')
            
            # Downloading latest staking-deposit-cli release files
            download_path = Path(Path.home(), 'ethwizard', 'downloads')
            download_path.mkdir(parents=True, exist_ok=True)

            binary_path = Path(download_path, binary_asset['file_name'])
            binary_hash = hashlib.sha256()

            try:
                with open(binary_path, 'wb') as binary_file:
                    with httpx.stream('GET', binary_asset['file_url'],
                        follow_redirects=True) as http_stream:
                        if http_stream.status_code != 200:
                            log.error(f'HTTP error while downloading staking-deposit-cli binary '
                                f'from Github. Status code {http_stream.status_code}')
                            return False
                        for data in http_stream.iter_bytes():
                            binary_file.write(data)
                            if checksum_asset is not None:
                                binary_hash.update(data)
            except httpx.RequestError as exception:
                log.error(f'Exception while downloading staking-deposit-cli binary from '
                    f'Github. {exception}')
                return False

            if checksum_asset is not None:
                binary_hexdigest = binary_hash.hexdigest().lower()

                checksum_path = Path(download_path, checksum_asset['file_name'])

                try:
                    with open(checksum_path, 'wb') as signature_file:
                        with httpx.stream('GET', checksum_asset['file_url'],
                            follow_redirects=True) as http_stream:
                            if http_stream.status_code != 200:
                                log.error(f'HTTP error while downloading staking-deposit-cli '
                                    f'checksum from Github. Status code {http_stream.status_code}')
                                return False
                            for data in http_stream.iter_bytes():
                                signature_file.write(data)
                except httpx.RequestError as exception:
                    log.error(f'Exception while downloading staking-deposit-cli checksum from '
                    f'Github. {exception}')
                    return False

                # Verify SHA256 signature
                with open(checksum_path, 'r') as checksum_file:
                    checksum = checksum_file.read(1024).strip().lower()
                    if binary_hexdigest != checksum:
                        # SHA256 checksum failed
                        log.error(f'SHA256 checksum failed on staking-deposit-cli binary from '
                            f'Github. Expected {checksum} but we got {binary_hexdigest}. We will '
                            f'stop here to protect you.')
                        return False
                    
                    log.info('Good SHA256 checksum for staking-deposit-cli binary.')
            
            # Extracting the staking-deposit-cli binary archive
            staking_deposit_cli_path.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                'tar', 'xvf', binary_path, '--strip-components', '2', '--directory',
                staking_deposit_cli_path])
            
            # Remove download leftovers
            binary_path.unlink()
            if checksum_path is not None:
                checksum_path.unlink()

        # Clean potential leftover keys
        if validator_keys_path.is_dir():
            shutil.rmtree(validator_keys_path)

        command = [staking_deposit_cli_binary, 'new-mnemonic', '--chain', network]

        # Ask for withdrawal address
        withdrawal_address = select_withdrawal_address(log)
        if withdrawal_address is None or withdrawal_address is False:
            return False
        
        if withdrawal_address != '':
            command.extend(['--execution_address', withdrawal_address])

        # Launch staking-deposit-cli
        log.info('Generating keys with staking-deposit-cli binary...')
        subprocess.run(command, cwd=staking_deposit_cli_path)

        # Clean up staking-deposit-cli binary
        staking_deposit_cli_binary.unlink()

        # Verify the generated keys
        generated_keys = search_for_generated_keys(validator_keys_path)
        
        if (
            generated_keys['deposit_data_path'] is None or
            len(generated_keys['keystore_paths']) == 0):
            log.warning('No key has been generated with the staking-deposit-cli tool.')
        else:
            actual_keys = generated_keys
            obtained_keys = True

    return actual_keys

def install_lighthouse_validator(network, keys, fee_recipient_address, mevboost_installed):
    # Import keystore(s) and configure the Lighthouse validator client
    # Returns a list of public keys when done

    # Check for existing systemd service
    lighthouse_vc_service_exists = False
    lighthouse_vc_service_name = LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME
    lighthouse_datadir = Path('/var/lib/lighthouse')

    service_details = get_systemd_service_details(lighthouse_vc_service_name)

    if service_details['LoadState'] == 'loaded':
        lighthouse_vc_service_exists = True
    
    if lighthouse_vc_service_exists:
        result = button_dialog(
            title='Lighthouse validator client service found',
            text=(
f'''
The lighthouse validator client service seems to have already been created.
Here are some details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

Do you want to skip installing and configuring the lighthouse validator
client?
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
            public_keys = []

            process_result = subprocess.run([
                LIGHTHOUSE_INSTALLED_PATH, '--network', network, 'account', 'validator', 'list',
                '--datadir', lighthouse_datadir
                ], capture_output=True, text=True)
            if process_result.returncode == 0:
                process_output = process_result.stdout
                public_keys = re.findall(r'0x[0-9a-f]{96}', process_output)
                public_keys = list(map(lambda x: x.strip(), public_keys))
            
            return public_keys
        
        # User wants to proceed, make sure the lighthouse validator service is stopped first
        subprocess.run([
            'systemctl', 'stop', lighthouse_vc_service_name])

    passwordless_check = True
    lighthouse_datadir_vc = Path('/var/lib/lighthouse/validators')
    public_keys = []

    while passwordless_check:

        result = button_dialog(
            title='Lighthouse validator client installation',
            text=(HTML(
'''
This next step will import your keystore(s) to be used with the Lighthouse
validator client and it will configure the Lighthouse validator client.

During the importation process, you will be asked to enter the password
you typed during the keys generation step. It is not your mnemonic. <style bg="red" fg="black">Do not
omit typing your password during this importation process.</style>

It will create a systemd service that will automatically start the
Lighthouse validator client on reboot or if it crashes. The validator
client will be started, it will connect to your beacon node and it will be
ready to start validating once your validator(s) get activated.
'''     )),
            buttons=[
                ('Configure', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        # Check if lighthouse validators client user or directory already exists
        if lighthouse_datadir_vc.exists() and lighthouse_datadir_vc.is_dir():
            process_result = subprocess.run([
                'du', '-sh', lighthouse_datadir_vc
                ], capture_output=True, text=True)
            
            process_output = process_result.stdout
            lighthouse_datadir_vc_size = process_output.split('\t')[0]

            result = button_dialog(
                title='Lighthouse validator client data directory found',
                text=(
f'''
An existing lighthouse validator client data directory has been found. Here
are some details found:

Location: {lighthouse_datadir_vc}
Size: {lighthouse_datadir_vc_size}

Do you want to remove this directory first and start from nothing? Removing
this directory will also remove any key imported previously.
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
                shutil.rmtree(lighthouse_datadir_vc)

        lighthouse_vc_user_exists = False
        process_result = subprocess.run([
            'id', '-u', 'lighthousevalidator'
        ])
        lighthouse_vc_user_exists = (process_result.returncode == 0)

        # Setup Lighthouse validator client user and directory
        if not lighthouse_vc_user_exists:
            subprocess.run([
                'useradd', '--no-create-home', '--shell', '/bin/false', 'lighthousevalidator'])
        subprocess.run([
            'mkdir', '-p', lighthouse_datadir_vc])
        subprocess.run([
            'chown', '-R', 'lighthousevalidator:lighthousevalidator', lighthouse_datadir_vc])
        subprocess.run([
            'chmod', '700', lighthouse_datadir_vc])
        
        # Import keystore(s) if we have some
        if len(keys['keystore_paths']) > 0:
            subprocess.run([
                LIGHTHOUSE_INSTALLED_PATH, '--network', network, 'account', 'validator', 'import',
                '--directory', keys['validator_keys_path'], '--datadir', lighthouse_datadir])
        else:
            log.warning('No keystore files found to import. We\'ll guess they were already imported '
                'for now.')
            time.sleep(5)

        # Check for correct keystore(s) import
        public_keys = []

        process_result = subprocess.run([
            LIGHTHOUSE_INSTALLED_PATH, '--network', network, 'account', 'validator', 'list',
            '--datadir', lighthouse_datadir
            ], capture_output=True, text=True)
        if process_result.returncode == 0:
            process_output = process_result.stdout
            public_keys = re.findall(r'0x[0-9a-f]{96}', process_output)
            public_keys = list(map(lambda x: x.strip(), public_keys))
            
        if len(public_keys) == 0:
            # We have no key imported

            result = button_dialog(
                title='No validator key imported',
                text=(
f'''
It seems like no validator key has been imported.

We cannot continue here without validator keys imported by the lighthouse
validator client.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            return False

        # Check for imported keystore without a password

        vc_definitions_path = lighthouse_datadir_vc.joinpath('validator_definitions.yml')

        if not vc_definitions_path.is_file():
            log.error('No validator_definitions.yml found after importing keystores.')
            return False

        vc_validators = []

        with open(vc_definitions_path, 'r') as vc_definitions_file:
            vc_validators = safe_load(vc_definitions_file)
        
        passwordless_keystore = []

        for vc_validator in vc_validators:
            if (
                'voting_keystore_password' not in vc_validator and
                'voting_keystore_password_path' not in vc_validator
            ):
                passwordless_keystore.append(vc_validator['voting_public_key'])
        
        if len(passwordless_keystore) > 0:

            # Remove imported validators
            shutil.rmtree(lighthouse_datadir_vc)

            plural = ''
            verb_plural = 'was'
            if len(passwordless_keystore) > 1:
                plural = 's'
                verb_plural = 'were'

            result = button_dialog(
                title='Keystore imported without a password',
                text=(
f'''
It seems like {len(passwordless_keystore)} keystore{plural} {verb_plural} imported without a password.

The lighthouse validator client will not be able to start automatically
if the keystore is imported without a password. Please try again.
'''             ),
                buttons=[
                    ('Retry', 1),
                    ('Quit', False)
                ]
            ).run()

            if not result:
                return False
        else:
            passwordless_check = False

    # Clean up generated keys
    for keystore_path in keys['keystore_paths']:
        os.unlink(keystore_path)

    # Make sure validators directory is owned by the right user/group
    subprocess.run([
        'chown', '-R', 'lighthousevalidator:lighthousevalidator', lighthouse_datadir_vc])
    
    log.info(
f'''
We found {len(public_keys)} key(s) imported into the lighthouse validator client.
'''
    )
    time.sleep(5)

    # Get Lighthouse version
    lighthouse_found = False
    lighthouse_version = 'unknown'
    try:
        process_result = subprocess.run([
            'lighthouse', '--version'
            ], capture_output=True, text=True)
        lighthouse_found = True

        process_output = process_result.stdout
        result = re.search(r'Lighthouse (.*?)\n', process_output)
        if result:
            lighthouse_version = result.group(1).strip()
    except FileNotFoundError:
        pass

    addparams = []

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', lighthouse_version)
    if result:
        cleaned_lighthouse_version = parse_version(result.group(1).strip())
        target_lighthouse_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_LIGHTHOUSE])

        if cleaned_lighthouse_version >= target_lighthouse_version:
            merge_ready = True

    if merge_ready:
        addparams.append(f'--suggested-fee-recipient {fee_recipient_address}')
    
    if mevboost_installed:
        addparams.append(f'--builder-proposals')

    addparams_string = ''
    if len(addparams) > 0:
        addparams_string = ' ' + ' '.join(addparams)

    # Setup Lighthouse validator client systemd service
    with open('/etc/systemd/system/' + lighthouse_vc_service_name, 'w') as service_file:
        service_file.write(LIGHTHOUSE_VC_SERVICE_DEFINITION[network].format(addparams=addparams_string))
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', lighthouse_vc_service_name])
    subprocess.run([
        'systemctl', 'enable', lighthouse_vc_service_name])

    # Verify proper Lighthouse validator client installation
    delay = 6
    log.info(
f'''
We are giving the lighthouse validator client {delay} seconds to start before
testing it.

You might see some error and warn messages about your beacon node not being
synced or about a failure to download validator duties. Those message are
normal to see while your beacon node is syncing.
'''
    )
    time.sleep(delay)
    try:
        subprocess.run([
            'journalctl', '-o', 'cat', '-fu', lighthouse_vc_service_name
        ], timeout=30)
    except subprocess.TimeoutExpired:
        pass

    # Check if the Lighthouse validator client service is still running
    service_details = get_systemd_service_details(lighthouse_vc_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Lighthouse validator client service not running properly',
            text=(
f'''
The lighthouse validator client service we just created seems to have
issues. Here are some details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the lighthouse validator client service cannot be
started properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_vc_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your lighthouse validator client service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_vc_service_name}
'''
        )

        return False

    return public_keys

def install_nimbus_validator(network, keys, fee_recipient_address, mevboost_installed):
    # Import keystore(s) and configure the Nimbus validator client part
    # Returns a list of public keys when done

    # Check for existing systemd service
    nimbus_service_exists = False
    nimbus_service_name = NIMBUS_SYSTEMD_SERVICE_NAME
    nimbus_datadir = Path('/var/lib/nimbus')
    nimbus_username = 'nimbus'

    service_details = get_systemd_service_details(nimbus_service_name)

    if service_details['LoadState'] == 'loaded':
        nimbus_service_exists = True
    
    if not nimbus_service_exists:
        log.error('The Nimbus service is missing. You might need to reinstall it.')
        return False

    result = button_dialog(
        title='Nimbus validators',
        text=(HTML(
'''
This next step will import your keystore(s) to be used with Nimbus.

During the importation process, you will be asked to enter the password
you typed during the keys generation step. It is not your mnemonic.
'''     )),
        buttons=[
            ('Import', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Stop the Nimbus service
    subprocess.run([
        'systemctl', 'stop', nimbus_service_name])

    # Import keystore(s) if we have some
    if len(keys['keystore_paths']) > 0:
        process_result = subprocess.run([
            NIMBUS_INSTALLED_PATH,
            'deposits', 'import',
            f'--data-dir={nimbus_datadir}',
            keys['validator_keys_path']
        ])
        if process_result.returncode != 0:
            log.error('Unable to import keystore(s) with Nimbus.')
            return False
        
        subprocess.run([
            'chown', '-R', f'{nimbus_username}:{nimbus_username}', nimbus_datadir])
        
    else:
        log.warning('No keystore files found to import. We\'ll guess they were already imported '
            'for now.')
        time.sleep(5)

    # Check for correct keystore(s) import
    public_keys = []

    nimbus_validators_path = nimbus_datadir.joinpath('validators')

    with os.scandir(nimbus_validators_path) as it:
        for entry in it:
            if entry.name.startswith('.'):
                continue

            if entry.is_dir():
                result = re.search(r'0x[0-9a-f]{96}', entry.name)
                if result:
                    public_keys.append(result.group(0))

    if len(public_keys) < 1:
        log.error('No key imported into Nimbus.')
        return False

    # Clean up generated keys
    for keystore_path in keys['keystore_paths']:
        os.unlink(keystore_path)
    
    log.info(
f'''
We found {len(public_keys)} key(s) imported into Nimbus.
'''
    )

    # Get Nimbus version
    nimbus_found = False
    nimbus_version = 'unknown'
    try:
        process_result = subprocess.run([
            'nimbus_beacon_node', '--version'
            ], capture_output=True, text=True)
        nimbus_found = True

        process_output = process_result.stdout
        result = re.search(r'Nimbus beacon node v?(?P<version>[^-]+)', process_output)
        if result:
            nimbus_version = result.group('version').strip()
    except FileNotFoundError:
        pass

    if not nimbus_found:
        log.error('We cannot find Nimbus anymore.')
        return False

    # Configure the Nimbus service

    nimbus_service_content = ''

    with open('/etc/systemd/system/' + nimbus_service_name, 'r') as service_file:
        nimbus_service_content = service_file.read()

    result = re.search(r'ExecStart\s*=\s*(.*?)([^\\\n]*(\\\s+)?)*', nimbus_service_content)
    if not result:
        log.error('Cannot parse Nimbus service file.')
        return False
    
    exec_start = result.group(0)

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', nimbus_version)
    if result:
        cleaned_nimbus_version = parse_version(result.group(1).strip())
        target_nimbus_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_NIMBUS])

        if cleaned_nimbus_version >= target_nimbus_version:
            merge_ready = True

    if merge_ready:
        log.info('Adding suggested fee recipient to Nimbus service...')

        # Remove all --suggested-fee-recipient related configuration
        exec_start = re.sub(r'(\s*\\)?\s+--suggested-fee-recipient?\s*=?\s*\S+', '', exec_start)

        exec_start = exec_start + f' \\\n    --suggested-fee-recipient={fee_recipient_address}'

    # Update Nimbus service with new configuration options
    nimbus_service_content = re.sub(r'ExecStart\s*=\s*(.*?)([^\\\n]*(\\\s+)?)*',
        exec_start, nimbus_service_content)

    # Write back configuration
    with open('/etc/systemd/system/' + nimbus_service_name, 'w') as service_file:
        service_file.write(nimbus_service_content)

    # Restart Nimbus service
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', nimbus_service_name])

    # Verify proper Nimbus installation
    delay = 10
    log.info(
f'''
We are giving Nimbus {delay} seconds to start before testing it.
'''
    )
    time.sleep(delay)
    try:
        subprocess.run([
            'journalctl', '-o', 'cat', '-fu', nimbus_service_name
        ], timeout=16)
    except subprocess.TimeoutExpired:
        pass

    # Check if the Nimbus service is still running
    service_details = get_systemd_service_details(nimbus_service_name)

    if not (
        service_details['LoadState'] == 'loaded' and
        service_details['ActiveState'] == 'active' and
        service_details['SubState'] == 'running'
    ):

        result = button_dialog(
            title='Nimbus service not running properly',
            text=(
f'''
The Nimbus service we just started seems to have issues. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {nimbus_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nimbus service logs, type the following command:

$ sudo journalctl -ru {nimbus_service_name}
'''
        )

        return False

    return public_keys

def install_chrony():
    # Prompt the user to install chrony to improve time sync

    if is_package_installed('chrony'):
        return True
    
    result = button_dialog(
        title='Improve time synchronization',
        text=(
'''
Time synchronization is very important for a validator setup. Being out of
sync can lead to lower rewards and other undesirable results.

The default Network Time Synchronization service installed can be improved
by replacing it with chrony. This is a simple change that can significantly
improve your time sync configuration for your machine.

Would you like to improve your time synchronization?
'''     ),
        buttons=[
            ('Improve', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if result == 2:
        return True

    if not result:
        return result
    
    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'

    subprocess.run(['apt', '-y', 'install', 'chrony'], env=env)

    return True

def initiate_deposit(network, keys, consensus_client):
    # Initiate and explain the deposit on launchpad

    # Check if we have the deposit data file
    if keys['deposit_data_path'] is None:
        log.warning('No deposit file found. We will assume that the deposit was already performed.')

        return True

    # Check for syncing status before prompting for deposit

    service_name = UNKNOWN_VALUE

    if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        # Check if the Lighthouse beacon node service is still running
        lighthouse_bn_service_name = LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME
        service_name = lighthouse_bn_service_name

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
The lighthouse beacon node service we created seems to have issues.
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

            log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False

    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

        # Check if the Nimbus service is still running
        nimbus_service_name = NIMBUS_SYSTEMD_SERVICE_NAME
        service_name = nimbus_service_name

        service_details = get_systemd_service_details(nimbus_service_name)

        if not (
            service_details['LoadState'] == 'loaded' and
            service_details['ActiveState'] == 'active' and
            service_details['SubState'] == 'running'
        ):

            result = button_dialog(
                title='Nimbus service not running properly',
                text=(
f'''
The Nimbus service we created seems to have issues. Here are some details
found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {nimbus_service_name}
'''         ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Nimbus service logs, type the following command:

$ sudo journalctl -ru {nimbus_service_name}
'''
            )

            return False

    # Verify proper beacon node installation and syncing
    local_bn_http_base = 'http://127.0.0.1:5052'
    
    bn_version_query = BN_VERSION_EP
    bn_query_url = local_bn_http_base + bn_version_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(bn_query_url, headers=headers)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to beacon node',
            text=(
f'''
We could not connect to beacon node HTTP server. Here are some details
for this last test we tried to perform:

URL: {bn_query_url}
Method: GET
Headers: {headers}
Exception: {exception}

We cannot proceed if the beacon node HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your beacon node service logs, type the following command:

$ sudo journalctl -ru {service_name}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to beacon node',
            text=(
f'''
We could not connect to beacon node HTTP server. Here are some details
for this last test we tried to perform:

URL: {bn_query_url}
Method: GET
Headers: {headers}
Status code: {response.status_code}

We cannot proceed if the beacon node HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs with:

$ sudo journalctl -ru {service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your beacon node service logs, type the following command:

$ sudo journalctl -ru {service_name}
'''
        )

        return False
    
    is_fully_sync = False
    syncing_status = {
        'bn_is_fully_sync': False,
        'bn_is_syncing': False,
        'bn_head_slot': UNKNOWN_VALUE,
        'bn_sync_distance': UNKNOWN_VALUE,
        'bn_connected_peers': 0
    }

    while not is_fully_sync:

        # Verify proper beacon node syncing
        def verifying_callback(set_percentage, log_text, change_status, set_result, get_exited):
            bn_is_fully_sync = False
            bn_is_syncing = False
            bn_connected_peers = 0
            bn_head_slot = UNKNOWN_VALUE
            bn_sync_distance = UNKNOWN_VALUE

            set_result({
                'bn_is_fully_sync': bn_is_fully_sync,
                'bn_is_syncing': bn_is_syncing,
                'bn_head_slot': bn_head_slot,
                'bn_sync_distance': bn_sync_distance,
                'bn_connected_peers': bn_connected_peers
            })

            set_percentage(1)

            journalctl_cursor = None

            while True:

                if get_exited():
                    return {
                        'bn_is_fully_sync': bn_is_fully_sync,
                        'bn_is_syncing': bn_is_syncing,
                        'bn_head_slot': bn_head_slot,
                        'bn_sync_distance': bn_sync_distance,
                        'bn_connected_peers': bn_connected_peers
                    }

                # Output logs
                command = []
                first_display = True
                if journalctl_cursor is None:
                    command = ['journalctl', '--no-pager', '--show-cursor', '-q', '-n', '25',
                        '-o', 'cat', '-u', service_name]
                else:
                    command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                        '-o', 'cat', '--after-cursor=' + journalctl_cursor, '-u',
                        service_name]
                    first_display = False

                process_result = subprocess.run(command, capture_output=True, text=True)

                process_output = ''
                if process_result.returncode == 0:
                    process_output = process_result.stdout
                else:
                    log_text(f'Return code: {process_result.returncode} while calling journalctl.')

                # Parse journalctl cursor and remove it from process_output
                log_length = len(process_output)
                if log_length > 0:
                    result = re.search(r'-- cursor: (?P<cursor>[^\n]+)', process_output)
                    if result:
                        journalctl_cursor = result.group('cursor')
                        process_output = (
                            process_output[:result.start()] +
                            process_output[result.end():])
                        process_output = process_output.rstrip()
                
                        log_length = len(process_output)

                if log_length > 0:
                    if not first_display and process_output[0] != '\n':
                        process_output = '\n' + process_output
                    log_text(process_output)
                
                bn_syncing_query = BN_SYNCING_EP
                bn_query_url = local_bn_http_base + bn_syncing_query
                headers = {
                    'accept': 'application/json'
                }
                try:
                    response = httpx.get(bn_query_url, headers=headers)
                except httpx.RequestError as exception:
                    log_text(f'Exception: {exception} while querying beacon node.')
                    continue

                if response.status_code != 200:
                    log_text(
                        f'Status code: {response.status_code} while querying beacon node.')
                    continue
            
                response_json = response.json()
                syncing_json = response_json

                bn_peer_count_query = BN_PEER_COUNT_EP
                bn_query_url = (
                    local_bn_http_base + bn_peer_count_query)
                headers = {
                    'accept': 'application/json'
                }
                try:
                    response = httpx.get(bn_query_url, headers=headers)
                except httpx.RequestError as exception:
                    log_text(f'Exception: {exception} while querying beacon node.')
                    continue

                if response.status_code != 200:
                    log_text(
                        f'Status code: {response.status_code} while querying beacon node.')
                    continue

                response_json = response.json()
                peer_count_json = response_json

                if (
                    syncing_json and
                    'data' in syncing_json and
                    'is_syncing' in syncing_json['data']
                    ):
                    bn_is_syncing = bool(syncing_json['data']['is_syncing'])
                else:
                    bn_is_syncing = False
                
                if (
                    syncing_json and
                    'data' in syncing_json and
                    'head_slot' in syncing_json['data']
                    ):
                    bn_head_slot = int(syncing_json['data']['head_slot'])
                else:
                    bn_head_slot = UNKNOWN_VALUE

                if (
                    syncing_json and
                    'data' in syncing_json and
                    'sync_distance' in syncing_json['data']
                    ):
                    bn_sync_distance = int(syncing_json['data']['sync_distance'])
                else:
                    bn_sync_distance = UNKNOWN_VALUE

                bn_connected_peers = 0
                if (
                    peer_count_json and
                    'data' in peer_count_json and
                    'connected' in peer_count_json['data']
                    ):
                    bn_connected_peers = int(peer_count_json['data']['connected'])

                bn_is_fully_sync = bn_sync_distance == 0

                if bn_is_fully_sync:
                    set_percentage(100)
                else:
                    if type(bn_sync_distance) == int and type(bn_head_slot) == int:
                        max_head = bn_sync_distance + bn_head_slot
                        set_percentage(round(bn_head_slot / max_head * 100.0))
                    else:
                        set_percentage(1)

                change_status((
f'''
Syncing: {bn_is_syncing} (Head slot: {bn_head_slot}, Sync distance: {bn_sync_distance})
Connected Peers: {bn_connected_peers}
'''             ).strip())

                if bn_is_fully_sync:
                    return {
                        'bn_is_fully_sync': bn_is_fully_sync,
                        'bn_is_syncing': bn_is_syncing,
                        'bn_head_slot': bn_head_slot,
                        'bn_sync_distance': bn_sync_distance,
                        'bn_connected_peers': bn_connected_peers
                    }
                else:
                    set_result({
                        'bn_is_fully_sync': bn_is_fully_sync,
                        'bn_is_syncing': bn_is_syncing,
                        'bn_head_slot': bn_head_slot,
                        'bn_sync_distance': bn_sync_distance,
                        'bn_connected_peers': bn_connected_peers
                    })
                
                time.sleep(1)

        unknown_joining_queue = 'no join queue information found'

        network_queue_info = unknown_joining_queue

        headers = {
            'accept': 'application/json'
        }

        beaconcha_in_queue_query_url = (
            BEACONCHA_IN_URLS[network] + BEACONCHA_VALIDATOR_QUEUE_API_URL)
        try:
            response = httpx.get(beaconcha_in_queue_query_url, headers=headers,
                follow_redirects=True)

            if response.status_code != 200:
                log.error(f'Status code: {response.status_code} while querying beaconcha.in.')
            else:
                response_json = response.json()
                if (
                    response_json and
                    'data' in response_json and
                    'beaconchain_entering' in response_json['data']):

                    validators_entering = int(response_json['data']['beaconchain_entering'])
                    waiting_td = timedelta(days=validators_entering / 900.0)

                    network_queue_info = (
                        f'{validators_entering} validators waiting to join '
                        f'[{humanize.naturaldelta(waiting_td)}]'
                    )

        except httpx.RequestError as exception:
            log.error(f'Exception: {exception} while querying beaconcha.in.')

        result = progress_log_dialog(
            title='Verifying beacon node syncing status',
            text=(HTML(
f'''
It is a good idea to wait for your beacon node to be in sync before doing
the deposit so you do not miss any reward. Activating a validator after the
deposit takes around 15 hours unless the join queue is longer. There is
currently {network_queue_info} for the <b>{NETWORK_LABEL[network]}</b>
Ethereum network.
'''         )),
            status_text=(
'''
Syncing: Unknown (Head slot: Unknown, Sync distance: Unknown)
Connected Peers: Unknown
'''
            ).strip(),
            quit_text='Skip',
            run_callback=verifying_callback
        ).run()
        
        if not result:
            log.warning('Beacon node syncing wait was cancelled.')
            return False
        
        syncing_status = result

        if not result['bn_is_fully_sync']:
            # We could not get a proper result from Lighthouse
            result = button_dialog(
                title='Beacon node syncing wait interrupted',
                text=(HTML(
f'''
We were interrupted before we could confirm the beacon node was in sync.
Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

<style bg="red" fg="black"><b>WARNING</b></style>: Proceeding with the deposit without having a beacon node fully in
sync has the potential to make you miss some reward between the time your
validator is activated and your beacon node is fully in sync. Your validator
will only be able to perform its duties when your beacon node is fully in
sync.

You can choose to quit the wizard here and resume it in a few hours.
'''             )),
                buttons=[
                    ('Wait', 1),
                    ('Proceed', 2),
                    ('Quit', False),
                ]
            ).run()

            if not result:
                return False
            
            if result == 2:
                break
        else:
            is_fully_sync = True

    # Log beacon node status before prompting for deposit
    log.info(
f'''
Here is your beacon node status before doing the deposit:

Syncing: {syncing_status['bn_is_syncing']} (Head slot: {syncing_status['bn_head_slot']}, Sync distance: {syncing_status['bn_sync_distance']})
Connected Peers: {syncing_status['bn_connected_peers']}
'''
    )

    launchpad_url = LAUNCHPAD_URLS[network]
    currency = NETWORK_CURRENCY[network]

    # Create an easily accessible copy of the deposit file
    deposit_file_copy_path = Path('/tmp', 'deposit_data.json')
    shutil.copyfile(keys['deposit_data_path'], deposit_file_copy_path)
    os.chmod(deposit_file_copy_path, stat.S_IROTH)

    # TODO: Create an alternative way to easily obtain the deposit file with a simple HTTP server

    result = button_dialog(
        title='Deposit on the launchpad',
        text=(
f'''
This next step is to perform the 32 {currency} deposit(s) on the launchpad. In
order to do this deposit, you will need your deposit file which was created
during the key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

On the Ethereum Launchpad website, you will be asked a few questions and it
will explain some of the risks and mitigation strategies. Make sure to read
everything carefully and make sure you understand it all. When you are
ready, go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
'''     ),
        buttons=[
            ('I\'m done', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    public_keys = []

    with open(keys['deposit_data_path'], 'r') as deposit_data_file:
        deposit_data = json.loads(deposit_data_file.read(204800))
        
        for validator_data in deposit_data:
            if 'pubkey' not in validator_data:
                continue
            public_key = validator_data['pubkey']
            public_keys.append('0x' + public_key)
    
    if len(public_keys) == 0:
        log.error('No public key(s) found in the deposit file.')
        return False

    # Verify that the deposit was done correctly using beaconcha.in API
    validator_deposits = get_bc_validator_deposits(network, public_keys, log)

    if type(validator_deposits) is not list and not validator_deposits:
        log.warning('Unable to get validator(s) deposits from beaconcha.in')
        validator_deposits = []

    skipping_deposit_check = False

    while not skipping_deposit_check and len(validator_deposits) == 0:
        # beaconcha.in does not see any validator with the public keys we generated

        result = button_dialog(
            title='No deposit found',
            text=(
f'''
No deposit has been found on the beaconcha.in website for the validator
keys that you generated. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', 2),
                ('Skip', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            skipping_deposit_check = True
            break

        validator_deposits = get_bc_validator_deposits(network, public_keys, log)

        if type(validator_deposits) is not list and not validator_deposits:
            log.warning('Unable to get validator(s) deposits from beaconcha.in')
            validator_deposits = []
    
    # Check if all the deposit(s) were done for each validator
    while not skipping_deposit_check and len(validator_deposits) < len(public_keys):

        result = button_dialog(
            title='Missing deposit(s)',
            text=(
f'''
Only {len(validator_deposits)} deposit(s) has been found for your {len(public_keys)} validators on the
beaconcha.in website. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', 2),
                ('Skip', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            skipping_deposit_check = True
            break

        validator_deposits = get_bc_validator_deposits(network, public_keys, log)

        if type(validator_deposits) is not list and not validator_deposits:
            log.warning('Unable to get validator(s) deposits from beaconcha.in')
            validator_deposits = []

    # Clean up deposit data file
    if not skipping_deposit_check:
        deposit_file_copy_path.unlink()
    else:
        log.warning(
f'''
We could not verify that your deposit was completed. Make sure to keep a copy of your deposit file in
{deposit_file_copy_path}
'''.strip())

    os.unlink(keys['deposit_data_path'])
    
    return public_keys
