import subprocess
import time
import httpx
import humanize
import re
import os
import shlex
import shutil
import json
import hashlib
import winreg
import io

from pathlib import Path

from packaging.version import parse as parse_version

from yaml import safe_load

from urllib.parse import urljoin, urlparse

from datetime import datetime, timedelta

from defusedxml import ElementTree

from dateutil.parser import parse as dateparse

from bs4 import BeautifulSoup

from rfc3986 import builder as urlbuilder

from zipfile import ZipFile

from functools import partial

from ethwizard.constants import *

from ethwizard.platforms.common import (
    select_network,
    select_mev_min_bid,
    select_mev_relays,
    select_custom_ports,
    select_consensus_checkpoint_provider,
    select_eth1_fallbacks,
    input_dialog_default,
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

from ethwizard.platforms.windows.common import (
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

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, input_dialog

def installation_steps(*args, **kwargs):

    def select_directory_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY

        if selected_directory not in context:
            context[selected_directory] = select_directory()
            step_sequence.save_state(step.step_id, context)

        if not context[selected_directory]:
            # User asked to quit
            del context[selected_directory]
            step_sequence.save_state(step.step_id, context)

            quit_app()
        
        return context

    select_directory_step = Step(
        step_id=SELECT_DIRECTORY_STEP_ID,
        display_name='Ethereum directory selection',
        exc_function=select_directory_function
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

    def create_firewall_rule_function(step, context, step_sequence):
        # Context variables
        selected_ports = CTX_SELECTED_PORTS

        if not (
            test_context_variable(context, selected_ports, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        if not create_firewall_rule(context[selected_ports]):
            # User asked to quit or error
            quit_app()
        
        return context

    create_firewall_rule_step = Step(
        step_id=CREATE_FIREWALL_RULE_STEP_ID,
        display_name='Firewall rules creation',
        exc_function=create_firewall_rule_function
    )

    def install_chocolatey_function(step, context, step_sequence):

        if not install_chocolatey():
            # We could not install chocolatey
            quit_app()

        return context

    install_chocolatey_step = Step(
        step_id=INSTALL_CHOCOLATEY_STEP_ID,
        display_name='Chocolatey installation',
        exc_function=install_chocolatey_function
    )

    def install_nssm_function(step, context, step_sequence):

        if not install_nssm():
            # We could not install nssm
            quit_app()

        return context
    
    install_nssm_step = Step(
        step_id=INSTALL_NSSM_STEP_ID,
        display_name='NSSM installation',
        exc_function=install_nssm_function
    )

    def install_execution_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
        execution_improved_service_timeout = CTX_EXECUTION_IMPROVED_SERVICE_TIMEOUT

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_ports, log) and
            test_context_variable(context, selected_execution_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        execution_client = context[selected_execution_client]

        if execution_client == EXECUTION_CLIENT_GETH:

            if not install_geth(context[selected_directory], context[selected_network],
                context[selected_ports]):
                # User asked to quit or error
                quit_app()
        
        elif execution_client == EXECUTION_CLIENT_NETHERMIND:
        
            if not install_nethermind(context[selected_directory], context[selected_network],
                context[selected_ports]):
                # User asked to quit or error
                quit_app()
        
        context[execution_improved_service_timeout] = True

        return context
    
    install_execution_step = Step(
        step_id=INSTALL_EXECUTION_STEP_ID,
        display_name='Execution client installation',
        exc_function=install_execution_function
    )

    def install_mevboost_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        mevboost_installed = CTX_MEVBOOST_INSTALLED

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        installed_value = install_mevboost(context[selected_directory], context[selected_network])

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

    def obtain_keys_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]
        
        if obtained_keys not in context:
            context[obtained_keys] = obtain_keys(context[selected_directory],
                context[selected_network], consensus_client)
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

    def detect_merge_ready_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        merge_ready_network = CTX_MERGE_READY_NETWORK

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()

        context[merge_ready_network] = detect_merge_ready(context[selected_directory],
            context[selected_network])
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
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS
        selected_eth1_fallbacks = CTX_SELECTED_ETH1_FALLBACKS
        selected_consensus_checkpoint_url = CTX_SELECTED_CONSENSUS_CHECKPOINT_URL
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
        consensus_improved_service_timeout = CTX_CONSENSUS_IMPROVED_SERVICE_TIMEOUT
        mevboost_installed = CTX_MEVBOOST_INSTALLED

        if not (
            test_context_variable(context, selected_directory, log) and
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

        if consensus_client == CONSENSUS_CLIENT_TEKU:

            if not install_teku(context[selected_directory], context[selected_network],
                context[selected_eth1_fallbacks], context[selected_consensus_checkpoint_url],
                context[selected_ports], context[mevboost_installed]):
                # User asked to quit or error
                quit_app()
        
        elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

            if not install_nimbus(context[selected_directory], context[selected_network],
                context[selected_eth1_fallbacks], context[selected_consensus_checkpoint_url],
                context[selected_ports], context[mevboost_installed]):
                # User asked to quit or error
                quit_app()
        
        elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

            if not install_lighthouse(context[selected_directory], context[selected_network],
                context[selected_eth1_fallbacks], context[selected_consensus_checkpoint_url],
                context[selected_ports], context[mevboost_installed]):
                # User asked to quit or error
                quit_app()
        
        context[consensus_improved_service_timeout] = True

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

    def install_monitoring_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_consensus_client, log) and
            test_context_variable(context, selected_execution_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]
        execution_client = context[selected_execution_client]

        if not install_monitoring(context[selected_directory], consensus_client, execution_client):
            # User asked to quit or error
            quit_app()

        return context
    
    install_monitoring_step = Step(
        step_id=INSTALL_MONITORING_STEP_ID,
        display_name='Monitoring installation',
        exc_function=install_monitoring_function
    )

    def improve_time_sync_function(step, context, step_sequence):
        if not improve_time_sync():
            # User asked to quit or error
            quit_app()

        return context

    improve_time_sync_step = Step(
        step_id=IMPROVE_TIME_SYNC_STEP_ID,
        display_name='Improve time synchronization',
        exc_function=improve_time_sync_function
    )

    def disable_windows_updates_function(step, context, step_sequence):
        if not disable_windows_updates():
            # User asked to quit or error
            quit_app()

        return context

    disable_windows_updates_step = Step(
        step_id=DISABLE_WINDOWS_UPDATES_STEP_ID,
        display_name='Disable automatic Windows updates',
        exc_function=disable_windows_updates_function
    )

    def adjust_power_plan_function(step, context, step_sequence):
        if not adjust_power_plan():
            # User asked to quit or error
            quit_app()

        return context

    adjust_power_plan_step = Step(
        step_id=ADJUST_POWER_PLAN_STEP_ID,
        display_name='Adjust power plan',
        exc_function=adjust_power_plan_function
    )

    def initiate_deposit_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]
        
        if not initiate_deposit(context[selected_directory], context[selected_network],
            context[obtained_keys], consensus_client):
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

        consensus_client = select_consensus_client(SUPPORTED_WINDOWS_CONSENSUS_CLIENTS)

        if not consensus_client:
            quit_app()
        
        context[selected_consensus_client] = consensus_client

        return context
    
    select_consensus_client_step = Step(
        step_id=SELECT_CONSENSUS_CLIENT_STEP_ID,
        display_name='Select consensus client',
        exc_function=select_consensus_client_function
    )

    def install_validator_function(step, context, step_sequence):
        # Context variables
        selected_directory = CTX_SELECTED_DIRECTORY
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS       
        selected_fee_recipient_address = CTX_SELECTED_FEE_RECIPIENT_ADDRESS
        public_keys = CTX_PUBLIC_KEYS
        mevboost_installed = CTX_MEVBOOST_INSTALLED
        selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

        if not (
            test_context_variable(context, selected_directory, log) and
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, selected_fee_recipient_address, log) and
            test_context_variable(context, mevboost_installed, log) and
            test_context_variable(context, selected_consensus_client, log)
            ):
            # We are missing context variables, we cannot continue
            quit_app()
        
        consensus_client = context[selected_consensus_client]

        if consensus_client == CONSENSUS_CLIENT_TEKU:
            # Install Teku validator client
            context[public_keys] = install_teku_validator(context[selected_directory],
                context[selected_network], context[obtained_keys],
                context[selected_fee_recipient_address], context[mevboost_installed])

        elif consensus_client == CONSENSUS_CLIENT_NIMBUS:
            # Install Nimbus validator client
            context[public_keys] = install_nimbus_validator(context[selected_directory],
                context[selected_network], context[obtained_keys],
                context[selected_fee_recipient_address], context[mevboost_installed])
        
        elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:
            # Install Lighthouse validator client
            context[public_keys] = install_lighthouse_validator(context[selected_directory],
                context[selected_network], context[obtained_keys],
                context[selected_fee_recipient_address], context[mevboost_installed])

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

    def select_execution_client_function(step, context, step_sequence):
        # Context variables
        selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT

        execution_client = select_execution_client(SUPPORTED_WINDOWS_EXECUTION_CLIENTS)

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
        select_directory_step,
        select_network_step,
        select_consensus_client_step,
        select_execution_client_step,
        install_chocolatey_step,
        install_nssm_step,
        install_mevboost_step,
        select_custom_ports_step,
        create_firewall_rule_step,
        detect_merge_ready_step,
        select_consensus_checkpoint_url_step,
        select_eth1_fallbacks_step,
        install_consensus_step,
        install_execution_step,
        test_open_ports_step,
        obtain_keys_step,
        select_fee_recipient_address_step,
        install_validator_step,
        install_monitoring_step,
        improve_time_sync_step,
        disable_windows_updates_step,
        adjust_power_plan_step,
        initiate_deposit_step,
        show_whats_next_step,
        show_public_keys_step
    ]

def create_firewall_rule(ports):
    # Add rules to Windows Firewall to make sure we can accept connections on clients ports

    execution_rule_name = 'Ethereum execution client'

    ec_tcp_rule_name = f'{execution_rule_name} TCP'
    ec_udp_rule_name = f'{execution_rule_name} UDP'

    log.info('Checking if we have a TCP firewall rule for the execution client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={ec_tcp_rule_name}'
    ])
    if process_result.returncode == 0:
        log.info('Deleting existing TCP firewall rule for the execution client before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={ec_tcp_rule_name}'
        ])
    log.info('Creating a new TCP firewall rule for the execution client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={ec_tcp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=tcp',
        f'localport={ports["eth1"]}'
    ])

    log.info('Checking if we have a UDP firewall rule for the execution client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={ec_udp_rule_name}'
    ])
    if process_result.returncode == 0:
        log.info('Deleting existing UDP firewall rule for the execution client before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={ec_udp_rule_name}'
        ])
    log.info('Creating a new UDP firewall rule for the execution client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={ec_udp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=udp',
        f'localport={ports["eth1"]}'
    ])

    consensus_rule_name = 'Ethereum consensus client'

    cc_tcp_rule_name = f'{consensus_rule_name} TCP'
    cc_udp_rule_name = f'{consensus_rule_name} UDP'

    log.info('Checking if we have a TCP firewall rule for the consensus client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={cc_tcp_rule_name}'
    ])
    if process_result.returncode == 0:
        log.info('Deleting existing TCP firewall rule for the consensus client before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={cc_tcp_rule_name}'
        ])
    log.info('Creating a new TCP firewall rule for the consensus client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={cc_tcp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=tcp',
        f'localport={ports["eth2_bn"]}'
    ])

    log.info('Checking if we have a UDP firewall rule for the consensus client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={cc_udp_rule_name}'
    ])
    if process_result.returncode == 0:
        log.info('Deleting existing UDP firewall rule for the consensus client before creating the new one...')
        subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={cc_udp_rule_name}'
        ])
    log.info('Creating a new UDP firewall rule for the consensus client...')
    process_result = subprocess.run([
        'netsh', 'advfirewall', 'firewall', 'add', 'rule',
        f'name={cc_udp_rule_name}',
        'dir=in',
        'action=allow',
        'service=any',
        'profile=any',
        'protocol=udp',
        f'localport={ports["eth2_bn"]}'
    ])

    return True

def install_chocolatey():
    # Install chocolatey to obtain other tools

    # Check to see if choco is already installed
    choco_installed = False

    try:
        process_result = subprocess.run(['choco', '--version'])

        if process_result.returncode == 0:
            choco_installed = True
            
            log.warning('Chocolatey is already installed, we will update it to the latest version')
            subprocess.run([
                'choco', 'upgrade', 'chocolatey', '-y'])

    except FileNotFoundError:
        choco_installed = False

    if choco_installed:
        return True

    log.info('Chocolatey is not installed, we will install it')
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
            process_result = subprocess.run([str(nssm_path), '--version'])

            if process_result.returncode == 0:
                nssm_installed = True
        except FileNotFoundError:
            nssm_installed = False
    
    if nssm_installed:
        log.info('NSSM is already installed, no need to install it')
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
            process_result = subprocess.run([str(choco_path), '--version'])

            if process_result.returncode == 0:
                choco_installed = True
        except FileNotFoundError:
            choco_installed = False

    if not choco_installed:
        log.error('We could not find choco. You might need to close this '
            'window and restart the wizard to continue.')
        return False
    
    try:
        subprocess.run([
            'choco', 'install', '-y', 'nssm'])
    except FileNotFoundError:
        subprocess.run([
            str(choco_path), 'install', '-y', 'nssm'])
    
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

    return selected_directory

def directory_validator(directory):
    try:
        directory_path = Path(directory)
        directory_path.mkdir(parents=True, exist_ok=True)
        return directory_path.is_dir()
    except OSError:
        return False

    return False

def install_mevboost(base_directory, network):
    # Install mev-boost for the selected network

    installed_value = {
        'installed': False
    }

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    mevboost_service_exists = False
    mevboost_service_name = 'mevboost'

    service_details = get_service_details(nssm_binary, mevboost_service_name)

    if service_details is not None:
        mevboost_service_exists = True

    if mevboost_service_exists:
        result = button_dialog(
            title='MEV-Boost service found',
            text=(
f'''
The MEV-Boost service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

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
                str(nssm_binary), 'stop', mevboost_service_name])
            subprocess.run([
                str(nssm_binary), 'remove', mevboost_service_name, 'confirm'])

            installed_value['installed'] = False
            return installed_value
        
        # User wants to proceed, make sure the MEV-Boost service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', mevboost_service_name])

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

Once installed locally, it will create a system service that will
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

    # Check if MEV-Boost is already installed
    mevboost_path = base_directory.joinpath('bin', 'mev-boost.exe')

    mevboost_found = False
    mevboost_version = 'unknown'

    if mevboost_path.is_file():
        try:
            process_result = subprocess.run([
                str(mevboost_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            mevboost_found = True

            process_output = process_result.stdout
            result = re.search(r'mev-boost v?(\S+)', process_output)
            if result:
                mevboost_version = result.group(1).strip()

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
Location: {mevboost_path}

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

        subprocess.run(['tar', 'xvf', str(binary_path), '--directory', str(bin_path)])
        
        # Remove download leftovers
        binary_path.unlink()
        checksums_path.unlink()

        # Get MEV-Boost version
        try:
            process_result = subprocess.run([
                str(mevboost_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            mevboost_found = True

            process_output = process_result.stdout
            result = re.search(r'mev-boost v?(\S+)', process_output)
            if result:
                mevboost_version = result.group(1).strip()
        except FileNotFoundError:
            pass

    # Setup MEV-Boost service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    mevboost_stdout_log_path = log_path.joinpath('mevboost-service-stdout.log')
    mevboost_stderr_log_path = log_path.joinpath('mevboost-service-stderr.log')

    if mevboost_stdout_log_path.is_file():
        mevboost_stdout_log_path.unlink()
    if mevboost_stderr_log_path.is_file():
        mevboost_stderr_log_path.unlink()

    mevboost_arguments = MEVBOOST_ARGUMENTS[network]
    
    # Select a min-bid value

    min_bid = select_mev_min_bid(log)

    if min_bid is False or min_bid is None:
        return False

    if min_bid > 0:
        min_bid_value = f'{min_bid:.6f}'.rstrip('0').rstrip('.')
        mevboost_arguments.append(f'-min-bid {min_bid_value}')

    # Select relays

    relay_list = select_mev_relays(network, log)

    if not relay_list:
        return False

    for relay in relay_list:
        mevboost_arguments.append(f'-relay {relay}')

    parameters = {
        'DisplayName': MEVBOOST_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(mevboost_stdout_log_path),
        'AppStderr': str(mevboost_stderr_log_path)
    }

    if not create_service(nssm_binary, mevboost_service_name, mevboost_path, mevboost_arguments,
                          parameters):
        log.error('There was an issue creating the MEV-Boost service. We cannot continue.')
        return False
    
    log.info('Starting MEV-Boost service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', mevboost_service_name
    ])

    # Wait a little before checking for MEV-Boost syncing since it can be slow to start
    delay = 6
    log.info(f'We are giving MEV-Boost {delay} seconds to start before testing it.')
    time.sleep(delay)
    
    # Verify proper MEV-Boost service installation
    service_details = get_service_details(nssm_binary, mevboost_service_name)
    if not service_details:
        log.error('We could not find the MEV-Boost service we just created. We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='MEV-Boost service not running properly',
            text=(
f'''
The MEV-Boost service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the MEV-Boost service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see
the logs in:

{mevboost_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your MEV-Boost service logs, inspect the following file:

{mevboost_stdout_log_path}
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

def install_geth(base_directory, network, ports):
    # Install geth for the selected network

    base_directory = Path(base_directory)

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
            str(nssm_binary), 'stop', geth_service_name])

    result = button_dialog(
        title='Geth installation',
        text=(
'''
This next step will install Geth, an Ethereum execution client.

It will download the official binary, verify its PGP signature and extract
it for easy use.

Once the installation is completed, it will create a system service that
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
    geth_path = base_directory.joinpath('bin', 'geth.exe')

    geth_found = False
    geth_version = 'unknown'

    if geth_path.is_file():
        try:
            process_result = subprocess.run([
                str(geth_path), 'version'
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

        command_line = [str(gpg_binary_path), '--list-keys', '--with-colons',
            GETH_WINDOWS_PGP_KEY_ID]
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
                log.warning(
f'''
We failed to download the Geth Windows Builder PGP key to verify the geth
archive after {retry_count} retries. We will skip signature verification.
'''
                )
            else:
                process_result = subprocess.run([
                    str(gpg_binary_path), '--verify', str(geth_archive_sig_path)])
                if process_result.returncode != 0:
                    log.error('The geth archive signature is wrong. We\'ll stop here to protect you.')
                    return False
        else:
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

        # Move geth back into bin directory
        target_geth_binary_path = bin_path.joinpath('geth.exe')
        if target_geth_binary_path.is_file():
            target_geth_binary_path.unlink()
        
        geth_extracted_binary.rename(target_geth_binary_path)

        geth_extracted_binary.parent.rmdir()

        # Get Geth version
        if geth_path.is_file():
            try:
                process_result = subprocess.run([
                    str(geth_path), 'version'
                    ], capture_output=True, text=True, encoding='utf8')
                geth_found = True

                process_output = process_result.stdout
                result = re.search(r'Version: (.*?)\n', process_output)
                if result:
                    geth_version = result.group(1).strip()

            except FileNotFoundError:
                pass
    
    # Check if Geth directory already exists
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

    geth_stdout_log_path = log_path.joinpath('geth-service-stdout.log')
    geth_stderr_log_path = log_path.joinpath('geth-service-stderr.log')

    if geth_stdout_log_path.is_file():
        geth_stdout_log_path.unlink()
    if geth_stderr_log_path.is_file():
        geth_stderr_log_path.unlink()

    geth_arguments = GETH_ARGUMENTS[network]
    geth_arguments.append('--datadir')
    geth_arguments.append(f'"{geth_datadir}"')
    if ports['eth1'] != DEFAULT_GETH_PORT:
        geth_arguments.append('--port')
        geth_arguments.append(str(ports['eth1']))
    
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
        jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
        jwt_token_path = jwt_token_dir.joinpath('jwttoken')

        if not setup_jwt_token_file(base_directory):
            log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
            )

            return False
        
        geth_arguments.append('--authrpc.jwtsecret')
        geth_arguments.append(f'"{jwt_token_path}"')

    parameters = {
        'DisplayName': GETH_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(geth_stdout_log_path),
        'AppStderr': str(geth_stderr_log_path)
    }

    if not create_service(nssm_binary, geth_service_name, geth_path, geth_arguments, parameters):
        log.error('There was an issue creating the geth service. We cannot continue.')
        return False
    
    log.info('Starting geth service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', geth_service_name
    ])

    # Wait a little before checking for Geth syncing since it can be slow to start
    delay = 30
    log.info(f'We are giving Geth {delay} seconds to start before testing it.')
    time.sleep(delay)
    
    # Verify proper Geth service installation
    service_details = get_service_details(nssm_binary, geth_service_name)
    if not service_details:
        log.error('We could not find the geth service we just created. We cannot continue.')
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

        log.info(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
'''
        )

        return False

    # Verify proper Geth syncing
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

        log.info(
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

        log.info(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
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

        err_log_read_index = 0

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
            err_log_text = ''
            with open(geth_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(err_log_read_index)
                err_log_text = log_file.read()
                err_log_read_index = log_file.tell()

            err_log_length = len(err_log_text)
            if err_log_length > 0:
                log_text(err_log_text)

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
    
    if result.get('skipping', False):
        log.warning('Skipping Geth verification.')
        return True

    if not result:
        log.warning('Geth verification was cancelled.')
        return False

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
logs and fix any issue found there. You can see the logs in:

{geth_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your geth service logs, inspect the following file:

{geth_stderr_log_path}
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

def install_nethermind(base_directory, network, ports):
    # Install Nethermind for the selected network

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    nethermind_service_exists = False
    nethermind_service_name = 'nethermind'

    service_details = get_service_details(nssm_binary, nethermind_service_name)

    if service_details is not None:
        nethermind_service_exists = True

    if nethermind_service_exists:
        result = button_dialog(
            title='Nethermind service found',
            text=(
f'''
The Nethermind service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

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
            str(nssm_binary), 'stop', nethermind_service_name])

    result = button_dialog(
        title='Nethermind installation',
        text=(
'''
This next step will install Nethermind, an Ethereum execution client.

It will install it using the Windows Package Manager.

Once the installation is completed, it will create a system service that
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
    nethermind_dir = base_directory.joinpath('bin', 'Nethermind')
    nethermind_path = nethermind_dir.joinpath('nethermind.exe')
    old_nethermind_path = nethermind_dir.joinpath('Nethermind.Runner.exe')

    nethermind_found = False
    nethermind_version = 'unknown'

    found_nethermind_path = None

    if nethermind_path.is_file():
        found_nethermind_path = nethermind_path
    elif old_nethermind_path.is_file():
        found_nethermind_path = old_nethermind_path
    
    if found_nethermind_path is not None:
        try:
            process_result = subprocess.run([
                str(found_nethermind_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            nethermind_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (?P<version>[^-\+]+)', process_output)
            if result:
                nethermind_version = result.group('version').strip()

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
Location: {nethermind_path}

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
        # Install Nethermind using winget

        base_options = ['--disable-interactivity', '--accept-source-agreements',
            '--accept-package-agreements']

        uninstall_options = ['--disable-interactivity', '--accept-source-agreements']

        try:
            # Install prerequisites
            command = ['winget', 'install', 'Microsoft.VCRedist.2015+.x64'] + base_options
            subprocess.run(command)

            # Install Nethermind
            command = ['winget', 'uninstall', 'nethermind'] + uninstall_options
            subprocess.run(command)

            nethermind_dir.mkdir(parents=True, exist_ok=True)
            command = ['winget', 'install', 'nethermind', '-l', str(nethermind_dir)] + base_options

            process_result = subprocess.run(command)
            if process_result.returncode != 0:
                log.error(f'Unexpected return code from winget when installing Nethermind. '
                    f'Return code {process_result.returncode}')
                return False

        except FileNotFoundError:
            log.error('winget not found. Aborting.')
            return False

        # Get Nethermind version
        nethermind_found = False
        nethermind_version = 'unknown'

        try:
            process_result = subprocess.run([
                str(nethermind_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            nethermind_found = True

            process_output = process_result.stdout
            result = re.search(r'Version: (?P<version>[^-\+]+)', process_output)
            if result:
                nethermind_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    # Check if Nethermind directory already exists
    nethermind_datadir = base_directory.joinpath('var', 'lib', 'nethermind')
    if nethermind_datadir.is_dir():
        nethermind_datadir_size = sizeof_fmt(get_dir_size(nethermind_datadir))

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

    # Setup Nethermind directory
    nethermind_datadir.mkdir(parents=True, exist_ok=True)
    
    # Setup Nethermind service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    nethermind_stdout_log_path = log_path.joinpath('nethermind-service-stdout.log')
    nethermind_stderr_log_path = log_path.joinpath('nethermind-service-stderr.log')

    if nethermind_stdout_log_path.is_file():
        nethermind_stdout_log_path.unlink()
    if nethermind_stderr_log_path.is_file():
        nethermind_stderr_log_path.unlink()

    nethermind_arguments = NETHERMIND_ARGUMENTS[network]
    nethermind_arguments.append('--datadir')
    nethermind_arguments.append(f'"{nethermind_datadir}"')
    if ports['eth1'] != DEFAULT_NETHERMIND_PORT:
        nethermind_arguments.append('--Network.P2PPort')
        nethermind_arguments.append(f'{ports["eth1"]}')
        nethermind_arguments.append('--Network.DiscoveryPort')
        nethermind_arguments.append(f'{ports["eth1"]}')
    
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
        jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
        jwt_token_path = jwt_token_dir.joinpath('jwttoken')

        if not setup_jwt_token_file(base_directory):
            log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
            )

            return False
    
        nethermind_arguments.append('--JsonRpc.JwtSecretFile')
        nethermind_arguments.append(f'"{jwt_token_path}"')

    parameters = {
        'DisplayName': NETHERMIND_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(nethermind_stdout_log_path),
        'AppStderr': str(nethermind_stderr_log_path)
    }

    if not create_service(nssm_binary, nethermind_service_name, nethermind_path,
        nethermind_arguments, parameters):
        log.error('There was an issue creating the Nethermind service. We cannot continue.')
        return False
    
    log.info('Starting Nethermind service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', nethermind_service_name
    ])

    # Wait a little before checking for Nethermind syncing since it can be slow to start
    delay = 30
    log.info(f'We are giving Nethermind {delay} seconds to start before testing it.')
    time.sleep(delay)
    
    # Verify proper Nethermind service installation
    service_details = get_service_details(nssm_binary, nethermind_service_name)
    if not service_details:
        log.error('We could not find the Nethermind service we just created. We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Nethermind service not running properly',
            text=(
f'''
The Nethermind service we just created seems to have issues. Here are
some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Nethermind service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see
the logs in:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, inspect the following file:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
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
can see the logs in:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, inspect the following file:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
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
can see the logs in:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, inspect the following file:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
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

        out_log_read_index = 0
        err_log_read_index = 0

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
            out_log_text = ''
            with open(nethermind_stdout_log_path, 'r', encoding='utf8', errors='replace') as log_file:
                log_file.seek(out_log_read_index)
                out_log_text = log_file.read()
                out_log_read_index = log_file.tell()

            out_log_length = len(out_log_text)
            if out_log_length > 0:
                log_text(out_log_text)

            err_log_text = ''
            with open(nethermind_stderr_log_path, 'r', encoding='utf8', errors='replace') as log_file:
                log_file.seek(err_log_read_index)
                err_log_text = log_file.read()
                err_log_read_index = log_file.tell()

            err_log_length = len(err_log_text)
            if err_log_length > 0:
                log_text(err_log_text)

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
                if response.status_code not in (200, 503):
                    log_text(
                        f'Status code: {response.status_code} while querying Nethermind Health.')
                elif response.status_code == 200:
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
f'''
Healthy: Unknown
Connected Peers: {exe_connected_peers}
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
check the logs and fix any issue found there. You can see the logs in:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nethermind service logs, inspect the following file:

{nethermind_stdout_log_path}
{nethermind_stderr_log_path}
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

def create_service(nssm_binary, service_name, binary_path, binary_args, parameters=None):
    # Create a Windows service using NSSM and configure it

    # Stop the service first if it exists
    subprocess.run([
        str(nssm_binary), 'stop', service_name
    ])

    # Remove the service to make sure it does not exist
    subprocess.run([
        str(nssm_binary), 'remove', service_name, 'confirm'
    ])

    # Install the service
    process_result = subprocess.run([
        str(nssm_binary), 'install', service_name, str(binary_path)
        ] + binary_args)

    if process_result.returncode != 0:
        log.error(f'Unexpected return code from NSSM when installing a new service. '
            f'Return code {process_result.returncode}')
        return False

    # Set the correct timeout values for shutdown
    if not set_service_param(nssm_binary, service_name, 'AppStopMethodConsole', '180000'):
        return False
    if not set_service_param(nssm_binary, service_name, 'AppStopMethodWindow', '180000'):
        return False
    if not set_service_param(nssm_binary, service_name, 'AppStopMethodThreads', '180000'):
        return False

    # Set all the other parameters
    if parameters is not None:
        for param, value in parameters.items():
            if not set_service_param(nssm_binary, service_name, param, value):
                return False
    
    return True

def install_jre(base_directory):
    # Install Adoptium JRE

    # Check if jre is already installed
    jre_path = base_directory.joinpath('bin', 'jre')
    java_path = jre_path.joinpath('bin', 'java.exe')

    jre_found = False
    jre_version = 'unknown'

    if java_path.is_file():
        try:
            process_result = subprocess.run([
                str(java_path), '--version'
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
            log.info('Getting JRE builds...')

            response = httpx.get(ADOPTIUM_17_API_URL, params=ADOPTIUM_17_API_PARAMS,
                follow_redirects=True)

            if response.status_code != 200:
                log.error(f'Cannot connect to JRE builds URL {ADOPTIUM_17_API_URL}.\n'
                    f'Unexpected status code {response.status_code}')
                return False
            
            response_json = response.json()

            if (
                type(response_json) is not list or
                len(response_json) == 0 or
                type(response_json[0]) is not dict):
                log.error(f'Unexpected response from JRE builds URL {ADOPTIUM_17_API_URL}')
                return False
            
            binaries = response_json
            for binary in binaries:
                if 'binary' not in binary:
                    continue
                binary = binary['binary']
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
                    log.error(f'Unexpected response from JRE builds URL '
                        f'{ADOPTIUM_17_API_URL} in package')
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
            log.error(f'Cannot connect to JRE builds URL {ADOPTIUM_17_API_URL}.'
                f'\nException {exception}')
            return False

        if len(windows_builds) <= 0:
            log.error('No JRE builds found on adoptium.net. We cannot continue.')
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
                log.info(f'Downloading JRE archive {latest_build["name"]}...')
                with httpx.stream('GET', latest_build['link'],
                    follow_redirects=True) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'Cannot download JRE archive {latest_build["link"]}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            log.error(f'Exception while downloading JRE archive. Exception {exception}')
            return False
        
        # Unzip JRE archive
        archive_members = None

        log.info(f'Extracting JRE archive {latest_build["name"]}...')
        with ZipFile(jre_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        jre_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            log.error('No files found in JRE archive. We cannot continue.')
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
                str(java_path), '--version'
                ], capture_output=True, text=True, encoding='utf8')
            jre_found = True

            process_output = process_result.stdout
            result = re.search(r'OpenJDK Runtime Environment (.*?)\n', process_output)
            if result:
                jre_version = result.group(1).strip()

        except FileNotFoundError:
            pass
    
        if not jre_found:
            log.error(f'We could not find the java binary from the installed JRE in {java_path}. '
                f'We cannot continue.')
            return False
    
    return True

def detect_merge_ready(base_directory, network):
    is_merge_ready = True

    # All networks are merge ready now.

    return {'result': is_merge_ready}

def install_nimbus(base_directory, network, eth1_fallbacks, consensus_checkpoint_url, ports,
    mevboost_installed):
    # Install Nimbus for the selected network

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    nimbus_datadir = base_directory.joinpath('var', 'lib', 'nimbus')

    # Check for existing service
    nimbus_service_exists = False
    nimbus_service_name = 'nimbus'

    service_details = get_service_details(nssm_binary, nimbus_service_name)

    if service_details is not None:
        nimbus_service_exists = True
    
    if nimbus_service_exists:
        result = button_dialog(
            title='Nimbus service found',
            text=(
f'''
The Nimbus service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing Nimbus and its service?
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
        
        # User wants to proceed, make sure the Nimbus service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', nimbus_service_name])
    
    result = button_dialog(
        title='Nimbus installation',
        text=(
'''
This next step will install Nimbus, an Ethereum consensus client that
includes a beacon node and a validator client in the same binary
distribution.

It will download the official Nimbus binary distribution from GitHub and
it will extract it for easy use.

Once installed locally, it will create a service that will automatically
start Nimbus on reboot or if it crashes. The Nimbus client will be
started and you will start syncing with the Ethereum network. The Nimbus
client will automatically start validating once syncing is completed and
your validator(s) are activated.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Check if Nimbus is already installed
    nimbus_path = base_directory.joinpath('bin', 'nimbus_beacon_node.exe')

    nimbus_found = False
    nimbus_version = 'unknown'

    if nimbus_path.is_file():
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
    
    install_nimbus_binary = True

    if nimbus_found:
        result = button_dialog(
            title='Nimbus binary found',
            text=(
f'''
The Nimbus binary seems to have already been installed. Here are some
details found:

Version: {nimbus_version}
Location: {nimbus_path}

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

        # Get Nimbus version
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

    # Check if Nimbus directory already exists
    if nimbus_datadir.is_dir():

        # Correct permissions for reading
        subprocess.run([
            'icacls', str(nimbus_datadir), '/grant:r', 'Everyone:(F)', '/t'
        ])

        nimbus_datadir_size = sizeof_fmt(get_dir_size(nimbus_datadir))

        # Removing these added permissions
        dirs_to_explore = []
        dirs_explored = []

        dirs_to_explore.append(str(nimbus_datadir))
        
        while len(dirs_to_explore) > 0:
            next_dir = dirs_to_explore.pop()

            with os.scandir(next_dir) as it:
                for entry in it:
                    if entry.is_dir():
                        dirs_to_explore.append(entry.path)
                    elif entry.is_file():
                        subprocess.run([
                            'icacls', entry.path, '/remove:g', 'Everyone'
                        ])

            dirs_explored.append(next_dir)
        
        for directory in reversed(dirs_explored):
            subprocess.run([
                'icacls', directory, '/remove:g', 'Everyone'
            ])

        result = button_dialog(
            title='Nimbus data directory found',
            text=(
f'''
An existing Nimbus data directory has been found. Here are some
details found:

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
            subprocess.run([
                'icacls', str(nimbus_datadir), '/grant', 'Everyone:(F)', '/t'
            ])
            shutil.rmtree(nimbus_datadir)

    # Setup Nimbus directory
    nimbus_datadir.mkdir(parents=True, exist_ok=True)

    # Setup Nimbus data directory permission
    current_username = os.environ['USERNAME']
    current_userdomain = os.environ['USERDOMAIN']
    current_identity = f'{current_userdomain}\\{current_username}'
    datadir_perm = f'{current_identity}:(OI)(CI)(F)'
    datadir_perm_file = f'{current_identity}:(F)'

    subprocess.run([
        'icacls', str(nimbus_datadir), '/inheritance:r', '/grant:r', datadir_perm, '/t'
    ])

    # Rework preexisting permissions
    system_identity = 'SYSTEM'
    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(str(nimbus_datadir))
    
    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritance:r', '/grant:r', datadir_perm_file
                    ])
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', system_identity
                    ])

        dirs_explored.append(next_dir)
    
    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/remove:g', system_identity
        ])

    # Perform checkpoint sync
    if consensus_checkpoint_url != '':
        # Perform checkpoint sync with the trustedNodeSync command
        log.info('Initializing Nimbus with a checkpoint sync endpoint.')
        process_result = subprocess.run([
            str(nimbus_path),
            'trustedNodeSync',
            f'--network={network}',
            f'--data-dir={nimbus_datadir}',
            f'--trusted-node-url={consensus_checkpoint_url}',
            '--backfill=false'
        ])
        if process_result.returncode != 0:
            log.error('Unable to initialize Nimbus with a checkpoint sync endpoint.')
            return False

    # Protect imported keystore files and secrets
    datadir_perm = f'{system_identity}:(OI)(CI)(F)'
    secrets_perm = f'{system_identity}:(F)'
    
    # Set correct ACL permissions on data directory.
    data_dirs_to_explore = []
    data_dirs_explored = []

    data_dirs_to_explore.append(str(nimbus_datadir))

    while len(data_dirs_to_explore) > 0:
        next_dir = data_dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    data_dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritance:r', '/grant:r', secrets_perm
                    ])

        data_dirs_explored.append(next_dir)
    
    for directory in reversed(data_dirs_explored):
        subprocess.run([
            'icacls', directory, '/inheritance:r', '/grant:r', datadir_perm
        ])
    
    # Remove current identity permissions
    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(str(nimbus_datadir))

    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', current_identity
                    ])

        dirs_explored.append(next_dir)
    
    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/remove:g', current_identity
        ])

    # Setup Nimbus service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    nimbus_stdout_log_path = log_path.joinpath('nimbus-service-stdout.log')
    nimbus_stderr_log_path = log_path.joinpath('nimbus-service-stderr.log')

    if nimbus_stdout_log_path.is_file():
        nimbus_stdout_log_path.unlink()
    if nimbus_stderr_log_path.is_file():
        nimbus_stderr_log_path.unlink()

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', nimbus_version)
    if result:
        cleaned_nimbus_version = parse_version(result.group(1).strip())
        target_nimbus_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_NIMBUS])

        if cleaned_nimbus_version >= target_nimbus_version:
            merge_ready = True

    nimbus_arguments = NIMBUS_ARGUMENTS[network]

    if merge_ready:
        jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
        jwt_token_path = jwt_token_dir.joinpath('jwttoken')

        if not setup_jwt_token_file(base_directory):
            log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
            )

            return False
        
        nimbus_arguments.append(f'--jwt-secret={jwt_token_path}')

    local_eth1_endpoint = 'http://127.0.0.1:8545'
    eth1_endpoints_flag = '--web3-url='
    if merge_ready:
        local_eth1_endpoint = 'http://127.0.0.1:8551'

    eth1_endpoints = [local_eth1_endpoint] + eth1_fallbacks

    for endpoint in eth1_endpoints:
        nimbus_arguments.append(f'{eth1_endpoints_flag}{endpoint}')

    nimbus_arguments.append(f'--data-dir={nimbus_datadir}')

    if ports['eth2_bn'] != DEFAULT_NIMBUS_BN_PORT:
        nimbus_arguments.append(f'--tcp-port={ports["eth2_bn"]}')
        nimbus_arguments.append(f'--udp-port={ports["eth2_bn"]}')

    if mevboost_installed:
        nimbus_arguments.append('--payload-builder=true')
        nimbus_arguments.append('--payload-builder-url=http://127.0.0.1:18550')

    parameters = {
        'DisplayName': NIMBUS_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(nimbus_stdout_log_path),
        'AppStderr': str(nimbus_stderr_log_path),
        'AppStopMethodConsole': '1500'
    }

    if not create_service(nssm_binary, nimbus_service_name, str(nimbus_path), nimbus_arguments,
        parameters):
        log.error('There was an issue creating the Nimbus service. We cannot continue.')
        return False

    log.info('Starting Nimbus service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', nimbus_service_name
    ])

    delay = 30
    log.info(f'We are giving {delay} seconds for the Nimbus service to start properly.')
    time.sleep(delay)

    # Verify proper Nimbus service installation
    service_details = get_service_details(nssm_binary, nimbus_service_name)
    if not service_details:
        log.error('We could not find the Nimbus service we just created. '
            'We cannot continue.')
        return False

    if not (service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Nimbus service not running properly',
            text=(
f'''
The Nimbus service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', nimbus_service_name])

        log.info(
f'''
To examine your Nimbus service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''
        )

        return False

    # Verify proper Nimbus installation and syncing
    local_nimbus_http_base = 'http://127.0.0.1:5052'
    
    cc_version_query = BN_VERSION_EP
    cc_query_url = local_nimbus_http_base + cc_version_query
    headers = {
        'accept': 'application/json'
    }

    keep_retrying = True

    retry_index = 0
    retry_count = 10
    retry_delay = 30
    retry_delay_increase = 15
    last_exception = None
    last_status_code = None

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(cc_query_url, headers=headers, timeout=30)
        except httpx.RequestError as exception:
            last_exception = exception
            
            log.warning(f'Exception {exception} when trying to connect to Nimbus HTTP server on '
                f'{cc_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        if response.status_code != 200:
            last_status_code = response.status_code

            log.error(f'Error code {response.status_code} when trying to connect to Nimbus HTTP '
                f'server on {cc_query_url}')
            
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
                title='Cannot connect to Nimbus',
                text=(
f'''
We could not connect to Nimbus HTTP server. Here are some details for
this last test we tried to perform:

URL: {cc_query_url}
Method: GET
Headers: {headers}
Exception: {last_exception}

We cannot proceed if the Nimbus HTTP server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see
the logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Nimbus service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''
            )

            return False
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot connect to Nimbus',
                text=(
f'''
We could not connect to Nimbus HTTP server. Here are some details for
this last test we tried to perform:

URL: {cc_query_url}
Method: GET
Headers: {headers}
Status code: {last_status_code}

We cannot proceed if the Nimbus HTTP server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see
the logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Nimbus service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''
            )

            return False

    # Verify proper Nimbus syncing
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

        out_log_read_index = 0
        err_log_read_index = 0

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
            out_log_text = ''
            with open(nimbus_stdout_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(out_log_read_index)
                out_log_text = log_file.read()
                out_log_read_index = log_file.tell()
            
            err_log_text = ''
            with open(nimbus_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(err_log_read_index)
                err_log_text = log_file.read()
                err_log_read_index = log_file.tell()
            
            out_log_length = len(out_log_text)
            if out_log_length > 0:
                log_text(out_log_text)

            err_log_length = len(err_log_text)
            if err_log_length > 0:
                log_text(err_log_text)

            time.sleep(1)
            
            cc_syncing_query = BN_SYNCING_EP
            cc_query_url = local_nimbus_http_base + cc_syncing_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(cc_query_url, headers=headers, timeout=30)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nimbus.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Nimbus.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            cc_peers_query = BN_PEERS_EP
            cc_query_url = local_nimbus_http_base + cc_peers_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(cc_query_url, headers=headers, timeout=30)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Nimbus.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Nimbus.')
                continue

            response_json = response.json()
            peers_json = response_json

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
                peers_json and
                'data' in peers_json and
                type(peers_json['data']) is list
                ):
                for peer in peers_json['data']:
                    if 'state' not in peer:
                        continue
                    if peer['state'] == 'connected':
                        bn_connected_peers = bn_connected_peers + 1
            
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
We are waiting for Nimbus to sync or find enough peers to confirm that it
is working properly.
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
        log.warning('Nimbus service installation verification was cancelled.')
        return False

    if not result['bn_is_working']:
        # We could not get a proper result from the Nimbus
        result = button_dialog(
            title='Nimbus service installation verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the Nimbus service
installation. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

We cannot proceed if the Nimbus service is not installed properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Nimbus service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
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

def install_teku(base_directory, network, eth1_fallbacks, consensus_checkpoint_url, ports,
    mevboost_installed):
    # Install Teku for the selected network

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    teku_service_exists = False
    teku_service_name = 'teku'

    service_details = get_service_details(nssm_binary, teku_service_name)

    if service_details is not None:
        teku_service_exists = True
    
    if teku_service_exists:
        result = button_dialog(
            title='Teku service found',
            text=(
f'''
The teku service seems to have already been created. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing teku and its service?
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
        
        # User wants to proceed, make sure the teku service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', teku_service_name])

    result = button_dialog(
        title='Teku installation',
        text=(
'''
This next step will install Teku, an Ethereum consensus client that
includes a beacon node and a validator client in the same binary
distribution.

It will install AdoptOpenJDK, a Java Runtime Environment, it will download
the official Teku binary distribution from GitHub, it will verify its
checksum and it will extract it for easy use.

Once installed locally, it will create a service that will automatically
start Teku on reboot or if it crashes. The Teku client will be started and
you will start syncing with the Ethereum network. The Teku client will
automatically start validating once syncing is completed and your
validator(s) are activated.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    if not install_jre(base_directory):
        return False

    # Check if teku is already installed
    teku_path = base_directory.joinpath('bin', 'teku')
    teku_batch_file = teku_path.joinpath('bin', 'teku.bat')

    teku_found = False
    teku_version = 'unknown'

    java_home = base_directory.joinpath('bin', 'jre')

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
    
    install_teku_binary = True

    if teku_found:
        result = button_dialog(
            title='Teku binary distribution found',
            text=(
f'''
The teku binary distribution seems to have already been installed. Here are
some details found:

Version: {teku_version}
Location: {teku_path}

Do you want to skip installing the teku binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_teku_binary = (result == 2)
    
    if install_teku_binary:
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

    # Check if teku directory already exists
    teku_datadir = base_directory.joinpath('var', 'lib', 'teku')
    if teku_datadir.is_dir():
        teku_datadir_size = sizeof_fmt(get_dir_size(teku_datadir))

        result = button_dialog(
            title='Teku data directory found',
            text=(
f'''
An existing teku data directory has been found. Here are some
details found:

Location: {teku_datadir}
Size: {teku_datadir_size}

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
            shutil.rmtree(teku_datadir)

    # Setup teku directory
    teku_datadir.mkdir(parents=True, exist_ok=True)

    # Setup teku service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    heap_dump_path = base_directory.joinpath('var', 'dump', 'teku')
    heap_dump_path.mkdir(parents=True, exist_ok=True)

    teku_stdout_log_path = log_path.joinpath('teku-service-stdout.log')
    teku_stderr_log_path = log_path.joinpath('teku-service-stderr.log')

    if teku_stdout_log_path.is_file():
        teku_stdout_log_path.unlink()
    if teku_stderr_log_path.is_file():
        teku_stderr_log_path.unlink()

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', teku_version)
    if result:
        cleaned_teku_version = parse_version(result.group(1).strip())
        target_teku_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_TEKU])

        if cleaned_teku_version >= target_teku_version:
            merge_ready = True

    teku_arguments = TEKU_ARGUMENTS[network]

    if merge_ready:
        jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
        jwt_token_path = jwt_token_dir.joinpath('jwttoken')

        if not setup_jwt_token_file(base_directory):
            log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
            )

            return False
        
        teku_arguments.append(f'--ee-jwt-secret-file="{jwt_token_path}"')

    local_eth1_endpoint = 'http://127.0.0.1:8545'
    eth1_endpoints_flag = '--eth1-endpoints'
    if merge_ready:
        local_eth1_endpoint = 'http://127.0.0.1:8551'
        eth1_endpoints_flag = '--ee-endpoint'

    eth1_endpoints = [local_eth1_endpoint] + eth1_fallbacks
    
    teku_arguments.append(f'{eth1_endpoints_flag}=' + ','.join(eth1_endpoints))
    teku_arguments.append(f'--data-path="{teku_datadir}"')
    if consensus_checkpoint_url != '':
        base_url = urlbuilder.URIBuilder.from_uri(consensus_checkpoint_url)
        initial_state_url = base_url.add_path(BN_FINALIZED_STATE_URL).finalize().unsplit()

        teku_arguments.append('--initial-state=' + initial_state_url)
    if ports['eth2_bn'] != DEFAULT_TEKU_BN_PORT:
        teku_arguments.append('--p2p-port=' + str(ports['eth2_bn']))

    if mevboost_installed:
        teku_arguments.append('--validators-builder-registration-default-enabled=true')
        teku_arguments.append('--builder-endpoint="http://127.0.0.1:18550"')

    parameters = {
        'DisplayName': TEKU_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(teku_stdout_log_path),
        'AppStderr': str(teku_stderr_log_path),
        'AppEnvironmentExtra': [
            'JAVA_HOME=' + str(java_home),
            'JAVA_OPTS=-Xmx6g',
            'TEKU_OPTS=-XX:HeapDumpPath=' + str(heap_dump_path)
        ],
        'AppStopMethodConsole': '1500'
    }

    if not create_service(nssm_binary, teku_service_name, teku_batch_file, teku_arguments,
        parameters):
        log.error('There was an issue creating the teku service. We cannot continue.')
        return False

    log.info('Starting teku service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', teku_service_name
    ])

    delay = 45
    log.info(f'We are giving {delay} seconds for the teku service to start properly.')
    time.sleep(delay)

    # Verify proper Teku service installation
    service_details = get_service_details(nssm_binary, teku_service_name)
    if not service_details:
        log.error('We could not find the teku service we just created. '
            'We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Teku service not running properly',
            text=(
f'''
The teku service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the teku service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', teku_service_name])

        log.info(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    # Verify proper Teku installation and syncing
    local_teku_http_base = 'http://127.0.0.1:5051'
    
    teku_version_query = BN_VERSION_EP
    teku_query_url = local_teku_http_base + teku_version_query
    headers = {
        'accept': 'application/json'
    }

    keep_retrying = True

    retry_index = 0
    retry_count = 10
    retry_delay = 30
    retry_delay_increase = 15
    last_exception = None
    last_status_code = None

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(teku_query_url, headers=headers)
        except httpx.RequestError as exception:
            last_exception = exception
            
            log.warning(f'Exception {exception} when trying to connect to teku HTTP server on '
                f'{teku_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        if response.status_code != 200:
            last_status_code = response.status_code

            log.error(f'Error code {response.status_code} when trying to connect to teku HTTP '
                f'server on {teku_query_url}')
            
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
                title='Cannot connect to Teku',
                text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Exception: {last_exception}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot connect to Teku',
                text=(
f'''
We could not connect to teku HTTP server. Here are some details for this
last test we tried to perform:

URL: {teku_query_url}
Method: GET
Headers: {headers}
Status code: {last_status_code}

We cannot proceed if the teku HTTP server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False

    # Verify proper Teku syncing
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

        out_log_read_index = 0
        err_log_read_index = 0

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
            out_log_text = ''
            with open(teku_stdout_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(out_log_read_index)
                out_log_text = log_file.read()
                out_log_read_index = log_file.tell()
            
            err_log_text = ''
            with open(teku_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(err_log_read_index)
                err_log_text = log_file.read()
                err_log_read_index = log_file.tell()
            
            out_log_length = len(out_log_text)
            if out_log_length > 0:
                log_text(out_log_text)

            err_log_length = len(err_log_text)
            if err_log_length > 0:
                log_text(err_log_text)

            time.sleep(1)
            
            teku_syncing_query = BN_SYNCING_EP
            teku_query_url = local_teku_http_base + teku_syncing_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(teku_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Teku.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Teku.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            teku_peers_query = BN_PEERS_EP
            teku_query_url = local_teku_http_base + teku_peers_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(teku_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Teku.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Teku.')
                continue

            response_json = response.json()
            peers_json = response_json

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
                peers_json and
                'data' in peers_json and
                type(peers_json['data']) is list
                ):
                for peer in peers_json['data']:
                    if 'state' not in peer:
                        continue
                    if peer['state'] == 'connected':
                        bn_connected_peers = bn_connected_peers + 1
            
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
        title='Verifying proper Teku service installation',
        text=(
f'''
We are waiting for Teku to sync or find enough peers to confirm that it is
working properly.
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
        log.warning('Teku service installation verification was cancelled.')
        return False

    if not result['bn_is_working']:
        # We could not get a proper result from the Teku
        result = button_dialog(
            title='Teku service installation verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the teku service
installation. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

We cannot proceed if the teku service is not installed properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    log.info(
f'''
Teku is installed and working properly.

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}
''' )
    time.sleep(5)

    return True

def install_lighthouse(base_directory, network, eth1_fallbacks, consensus_checkpoint_url, ports,
    mevboost_installed):
    # Install Lighthouse for the selected network

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    lighthouse_datadir = base_directory.joinpath('var', 'lib', 'lighthouse')

    # Check for existing service
    lighthouse_service_exists = False
    lighthouse_service_name = 'lighthousebeacon'

    service_details = get_service_details(nssm_binary, lighthouse_service_name)

    if service_details is not None:
        lighthouse_service_exists = True
    
    if lighthouse_service_exists:
        result = button_dialog(
            title='Lighthouse beacon node service found',
            text=(
f'''
The Lighthouse beacon node service seems to have already been created.
Here are some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing Lighthouse and its service?
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
        
        # User wants to proceed, make sure the Lighthouse service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', lighthouse_service_name])
    
    result = button_dialog(
        title='Lighthouse installation',
        text=(
'''
This next step will install Lighthouse, an Ethereum consensus client that
includes a beacon node and a validator client in the same binary.

It will download the official binary from GitHub, verify its PGP signature
and extract it for easy use.

Once installed locally, it will create a service that will automatically
start the Lighthouse beacon node on reboot or if it crashes. The beacon
node will be started and you will slowly start syncing with the Ethereum
network. This syncing process can take a few hours or days even with good
hardware and good internet if you did not select a working checkpoint
sync endpoint.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Check if Lighthouse is already installed
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
    
    install_lighthouse_binary = True

    if lighthouse_found:
        result = button_dialog(
            title='Lighthouse binary found',
            text=(
f'''
The Lighthouse binary seems to have already been installed. Here are some
details found:

Version: {lighthouse_version}
Location: {lighthouse_path}

Do you want to skip installing the Lighthouse binary?
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
        
        # Extracting the Lighthouse binary archive
        subprocess.run([
            'tar', 'xvf', binary_path, '--directory', bin_path])
        
        # Remove download leftovers
        binary_path.unlink()

        # Get Lighthouse version
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

    # Check if Lighthouse directory already exists
    if lighthouse_datadir.is_dir():

        lighthouse_datadir_size = sizeof_fmt(get_dir_size(lighthouse_datadir))

        result = button_dialog(
            title='Lighthouse data directory found',
            text=(
f'''
An existing Lighthouse data directory has been found. Here are some
details found:

Location: {lighthouse_datadir}
Size: {lighthouse_datadir_size}

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
            shutil.rmtree(lighthouse_datadir)

    # Setup Lighthouse directory
    lighthouse_datadir.mkdir(parents=True, exist_ok=True)

    # Setup Lighthouse service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    lighthouse_stdout_log_path = log_path.joinpath('lighthouse-beacon-service-stdout.log')
    lighthouse_stderr_log_path = log_path.joinpath('lighthouse-beacon-service-stderr.log')

    if lighthouse_stdout_log_path.is_file():
        lighthouse_stdout_log_path.unlink()
    if lighthouse_stderr_log_path.is_file():
        lighthouse_stderr_log_path.unlink()

    # Check if merge ready
    merge_ready = False

    result = re.search(r'([^-]+)', lighthouse_version)
    if result:
        cleaned_lighthouse_version = parse_version(result.group(1).strip())
        target_lighthouse_version = parse_version(
            MIN_CLIENT_VERSION_FOR_MERGE[network][CONSENSUS_CLIENT_LIGHTHOUSE])

        if cleaned_lighthouse_version >= target_lighthouse_version:
            merge_ready = True

    lighthouse_bn_arguments = LIGHTHOUSE_BN_ARGUMENTS[network]

    if merge_ready:
        jwt_token_dir = base_directory.joinpath('var', 'lib', 'ethereum')
        jwt_token_path = jwt_token_dir.joinpath('jwttoken')

        if not setup_jwt_token_file(base_directory):
            log.error(
f'''
Unable to create JWT token file in {jwt_token_path}
'''
            )

            return False

        lighthouse_bn_arguments.append('--execution-jwt')
        lighthouse_bn_arguments.append(f'{jwt_token_path}')

    local_eth1_endpoint = 'http://127.0.0.1:8545'
    eth1_endpoints_flag = '--eth1-endpoints'
    if merge_ready:
        local_eth1_endpoint = 'http://127.0.0.1:8551'
        eth1_endpoints_flag = '--execution-endpoint'
    
    eth1_endpoints = [local_eth1_endpoint] + eth1_fallbacks
    eth1_endpoints_string = ','.join(eth1_endpoints)

    lighthouse_bn_arguments.append(f'{eth1_endpoints_flag}')
    lighthouse_bn_arguments.append(f'{eth1_endpoints_string}')

    lighthouse_bn_arguments.append('--datadir')
    lighthouse_bn_arguments.append(f'{lighthouse_datadir}')

    if ports['eth2_bn'] != DEFAULT_LIGHTHOUSE_BN_PORT:
        lighthouse_bn_arguments.append('--port')
        lighthouse_bn_arguments.append(f'{ports["eth2_bn"]}')
    
    if consensus_checkpoint_url != '':
        lighthouse_bn_arguments.append('--checkpoint-sync-url')
        lighthouse_bn_arguments.append(f'{consensus_checkpoint_url}')

    if mevboost_installed:
        lighthouse_bn_arguments.append('--builder')
        lighthouse_bn_arguments.append('http://127.0.0.1:18550')

    parameters = {
        'DisplayName': LIGHTHOUSE_BN_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(lighthouse_stdout_log_path),
        'AppStderr': str(lighthouse_stderr_log_path),
        'AppStopMethodConsole': '1500'
    }

    if not create_service(nssm_binary, lighthouse_service_name, str(lighthouse_path),
        lighthouse_bn_arguments, parameters):
        log.error('There was an issue creating the Lighthouse beacon node service. '
            'We cannot continue.')
        return False

    log.info('Starting Lighthouse beacon node service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', lighthouse_service_name
    ])

    delay = 30
    log.info(f'We are giving {delay} seconds for the Lighthouse beacon node service to start properly.')
    time.sleep(delay)

    # Verify proper Lighthouse service installation
    service_details = get_service_details(nssm_binary, lighthouse_service_name)
    if not service_details:
        log.error('We could not find the Lighthouse service we just created. '
            'We cannot continue.')
        return False

    if not (service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Lighthouse service not running properly',
            text=(
f'''
The Lighthouse service we just created seems to have issues. Here are
some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Lighthouse service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see
the logs in:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', lighthouse_service_name])

        log.info(
f'''
To examine your Lighthouse service logs, inspect the following files:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''
        )

        return False

    # Verify proper Lighthouse installation and syncing
    local_lighthouse_http_base = 'http://127.0.0.1:5052'
    
    cc_version_query = BN_VERSION_EP
    cc_query_url = local_lighthouse_http_base + cc_version_query
    headers = {
        'accept': 'application/json'
    }

    keep_retrying = True

    retry_index = 0
    retry_count = 10
    retry_delay = 30
    retry_delay_increase = 15
    last_exception = None
    last_status_code = None

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(cc_query_url, headers=headers)
        except httpx.RequestError as exception:
            last_exception = exception
            
            log.warning(f'Exception {exception} when trying to connect to Lighthouse HTTP server on '
                f'{cc_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            retry_delay = retry_delay + retry_delay_increase
            continue

        if response.status_code != 200:
            last_status_code = response.status_code

            log.error(f'Error code {response.status_code} when trying to connect to Lighthouse HTTP '
                f'server on {cc_query_url}')
            
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
                title='Cannot connect to Lighthouse',
                text=(
f'''
We could not connect to Lighthouse HTTP server. Here are some details for
this last test we tried to perform:

URL: {cc_query_url}
Method: GET
Headers: {headers}
Exception: {last_exception}

We cannot proceed if the Lighthouse HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Lighthouse service logs, inspect the following files:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''
            )

            return False
        elif last_status_code is not None:
            result = button_dialog(
                title='Cannot connect to Lighthouse',
                text=(
f'''
We could not connect to Lighthouse HTTP server. Here are some details for
this last test we tried to perform:

URL: {cc_query_url}
Method: GET
Headers: {headers}
Status code: {last_status_code}

We cannot proceed if the Lighthouse HTTP server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your Lighthouse service logs, inspect the following files:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''
            )

            return False

    # Verify proper Lighthouse syncing
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

        out_log_read_index = 0
        err_log_read_index = 0

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
            out_log_text = ''
            with open(lighthouse_stdout_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(out_log_read_index)
                out_log_text = log_file.read()
                out_log_read_index = log_file.tell()
            
            err_log_text = ''
            with open(lighthouse_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_file.seek(err_log_read_index)
                err_log_text = log_file.read()
                err_log_read_index = log_file.tell()
            
            out_log_length = len(out_log_text)
            if out_log_length > 0:
                log_text(out_log_text)

            err_log_length = len(err_log_text)
            if err_log_length > 0:
                log_text(err_log_text)

            time.sleep(1)
            
            cc_syncing_query = BN_SYNCING_EP
            cc_query_url = local_lighthouse_http_base + cc_syncing_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(cc_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Lighthouse.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Lighthouse.')
                continue
        
            response_json = response.json()
            syncing_json = response_json

            cc_peers_query = BN_PEERS_EP
            cc_query_url = local_lighthouse_http_base + cc_peers_query
            headers = {
                'accept': 'application/json'
            }
            try:
                response = httpx.get(cc_query_url, headers=headers)
            except httpx.RequestError as exception:
                log_text(f'Exception: {exception} while querying Lighthouse.')
                continue

            if response.status_code != 200:
                log_text(f'Status code: {response.status_code} while querying Lighthouse.')
                continue

            response_json = response.json()
            peers_json = response_json

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
                peers_json and
                'data' in peers_json and
                type(peers_json['data']) is list
                ):
                for peer in peers_json['data']:
                    if 'state' not in peer:
                        continue
                    if peer['state'] == 'connected':
                        bn_connected_peers = bn_connected_peers + 1
            
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
        title='Verifying proper Lighthouse service installation',
        text=(
f'''
We are waiting for Lighthouse to sync or find enough peers to confirm
that it is working properly.
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
        log.warning('Lighthouse service installation verification was cancelled.')
        return False

    if not result['bn_is_working']:
        # We could not get a proper result from the Lighthouse
        result = button_dialog(
            title='Lighthouse service installation verification interrupted',
            text=(
f'''
We were interrupted before we could fully verify the Lighthouse service
installation. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

We cannot proceed if the Lighthouse service is not installed properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your Lighthouse service logs, inspect the following files:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''
        )

        return False

    log.info(
f'''
Lighthouse is installed and working properly.

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}
''' )
    time.sleep(5)

    return True

def install_teku_validator(base_directory, network, keys, fee_recipient_address,
    mevboost_installed):
    # Import keystore(s) and configure the Teku validator client (as part of the same service)
    # Returns a list of public keys when done

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    teku_service_exists = False
    teku_service_name = 'teku'

    service_details = get_service_details(nssm_binary, teku_service_name)

    if service_details is not None:
        teku_service_exists = True
    
    if not teku_service_exists:
        log.error('The Teku service is missing. You might need to reinstall it.')
        return False

    # Stop the Teku service
    subprocess.run([
        str(nssm_binary), 'stop', teku_service_name])

    # List validator keys
    public_keys = []

    subprocess.run([
        'icacls', keys['validator_keys_path'], '/grant:r', 'Everyone:(F)', '/t'
    ])

    if len(keys['keystore_paths']) > 0:
        with os.scandir(keys['validator_keys_path']) as it:
            for entry in it:
                if not entry.is_file():
                    continue

                if not entry.name.startswith('keystore'):
                    continue

                if not entry.name.endswith('.json'):
                    continue

                with open(entry.path, 'r') as keystore_file:
                    keystore = json.loads(keystore_file.read(204800))
            
                    if 'pubkey' not in keystore:
                        log.error(f'No pubkey found in keystore file {entry.path}')
                        continue
                    
                    public_key = keystore['pubkey']
                    public_keys.append('0x' + public_key)

    else:
        log.error('No keystore files found. Teku will not be able to run any validator.'
            ' You will need to import or generate new validator keys.')
        return False

    if len(public_keys) < 1:
        log.error('No key found for Teku to run.')
        return False

    # Secure keys permission
    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(keys['validator_keys_path'])
    
    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', 'Everyone'
                    ])

        dirs_explored.append(next_dir)
    
    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/remove:g', 'Everyone'
        ])

    log.info(
f'''
We found {len(public_keys)} key(s) for Teku.
'''
    )
    
    # Adding configuration to the Teku service
    teku_arguments = shlex.split(service_details['parameters']['AppParameters'], posix=False)

    # Fee recipient configuration (--validators-proposer-default-fee-recipient)
    has_fee_recipient_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(teku_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = f'{fee_recipient_address}'
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
        log.info('Adding fee recipient to Teku...')

        teku_arguments.append(f'--validators-proposer-default-fee-recipient={fee_recipient_address}')
    else:
        log.warning('Teku was already configured with a fee recipient. We will try to update or make '
            'sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for fee recipient argument.')
            return False
        
        teku_arguments[replaced_index] = replaced_arg
    
    # Validator keys configuration (--validator-keys)
    has_validator_keys_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(teku_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = f'"{keys["validator_keys_path"]}";"{keys["validator_keys_path"]}"'
            break
        elif arg.lower().startswith('--validator-keys'):
            has_validator_keys_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--validator-keys="{keys["validator_keys_path"]}";"{keys["validator_keys_path"]}"'
                break
            else:
                replace_next = True

    if not has_validator_keys_config:
        log.info('Adding validator keys to Teku...')

        teku_arguments.append(f'--validator-keys="{keys["validator_keys_path"]}";"{keys["validator_keys_path"]}"')
    else:
        log.warning('Teku was already configured with a fee recipient. We will try to update or make '
            'sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for fee recipient argument.')
            return False
        
        teku_arguments[replaced_index] = replaced_arg
    
    # Updating Teku service configuration
    if not set_service_param(nssm_binary, teku_service_name, 'AppParameters', teku_arguments):
        return False

    log.info('Starting Teku service...')
    subprocess.run([
        str(nssm_binary), 'start', teku_service_name])

    delay = 45
    log.info(f'We are giving {delay} seconds for the Teku service to start properly.')
    time.sleep(delay)

    # Verify proper Teku service installation
    service_details = get_service_details(nssm_binary, teku_service_name)
    if not service_details:
        log.error('We could not find the Teku service we just modified. '
            'We cannot continue.')
        return False

    log_path = base_directory.joinpath('var', 'log')
    teku_stdout_log_path = log_path.joinpath('teku-service-stdout.log')
    teku_stderr_log_path = log_path.joinpath('teku-service-stderr.log')

    if not (service_details['status'] == WINDOWS_SERVICE_RUNNING):

        # Check for evidence of wrong password file
        if teku_stderr_log_path.is_file():
            log_part = ''
            with open(teku_stderr_log_path, 'r', encoding='utf8') as log_file:
                log_part = log_file.read(1024)
            result = re.search(r'Failed to decrypt', log_part)
            if result:
                subprocess.run([
                    str(nssm_binary), 'stop', teku_service_name])
                
                log.error(
f'''
Your password file contains the wrong password. Teku cannot be started. You
might need to generate your keys again or fix your password file. We cannot
continue.

Your password files are the .txt files in:

{keys['validator_keys_path']}
'''             )
                return False

        result = button_dialog(
            title='Teku service not running properly',
            text=(
f'''
The Teku service we just configured seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Teku service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', teku_service_name])

        log.info(
f'''
To examine your Teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
        )

        return False

    return public_keys

def install_nimbus_validator(base_directory, network, keys, fee_recipient_address,
    mevboost_installed):
    # Import keystore(s) and configure the Nimbus validator client (as part of the same service)
    # Returns a list of public keys when done

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    nimbus_path = base_directory.joinpath('bin', 'nimbus_beacon_node.exe')
    nimbus_datadir = base_directory.joinpath('var', 'lib', 'nimbus')
    nimbus_validators_path = nimbus_datadir.joinpath('validators')

    # Check for existing service
    nimbus_service_exists = False
    nimbus_service_name = 'nimbus'

    service_details = get_service_details(nssm_binary, nimbus_service_name)

    if service_details is not None:
        nimbus_service_exists = True
    
    if not nimbus_service_exists:
        log.error('The Nimbus service is missing. You might need to reinstall it.')
        return False

    # Import validator keys into Nimbus
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
        str(nssm_binary), 'stop', nimbus_service_name])

    # Import validator keys into nimbus
    subprocess.run([
        'icacls', keys['validator_keys_path'], '/grant:r', 'Everyone:(F)', '/t'
    ])

    # Correct permissions for reading and importing keys
    system_identity = 'SYSTEM'
    current_username = os.environ['USERNAME']
    current_userdomain = os.environ['USERDOMAIN']
    current_identity = f'{current_userdomain}\\{current_username}'
    datadir_perm = f'{current_identity}:(OI)(CI)(F)'
    datadir_perm_file = f'{current_identity}:(F)'

    subprocess.run([
        'icacls', str(nimbus_datadir), '/grant', 'Everyone:(F)', '/t'
    ])

    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(str(nimbus_datadir))

    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritance:r', '/grant:r', datadir_perm_file
                    ])
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', system_identity
                    ])
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', 'Everyone'
                    ])

        dirs_explored.append(next_dir)

    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/inheritance:r', '/grant:r', datadir_perm
        ])
        subprocess.run([
            'icacls', directory, '/remove:g', system_identity
        ])
        subprocess.run([
            'icacls', directory, '/remove:g', 'Everyone'
        ])

    if len(keys['keystore_paths']) > 0:
        process_result = subprocess.run([
            str(nimbus_path),
            'deposits', 'import',
            f'--data-dir={nimbus_datadir}',
            keys['validator_keys_path']
        ])
        if process_result.returncode != 0:
            log.error('Unable to import keystore(s) with Nimbus.')
            return False

    else:
        log.warning('No keystore files found to import. We\'ll guess they were already imported '
            'for now.')
        time.sleep(5)

    # Check for correct keystore(s) import
    public_keys = []

    if not nimbus_validators_path.is_dir():
        log.error('There is no imported keystore files for Nimbus. We cannot continue.')
        return False

    with os.scandir(nimbus_validators_path) as it:
        for entry in it:
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

    subprocess.run([
        'icacls', keys['validator_keys_path'], '/remove:g', 'Everyone', '/t'
    ])

    log.info(
f'''
We found {len(public_keys)} key(s) imported into Nimbus.
'''
    )

     # Protect imported keystore files and secrets
    datadir_perm = f'{system_identity}:(OI)(CI)(F)'
    secrets_perm = f'{system_identity}:(F)'

    # Set correct ACL permissions on data directory.
    data_dirs_to_explore = []
    data_dirs_explored = []

    data_dirs_to_explore.append(str(nimbus_datadir))

    while len(data_dirs_to_explore) > 0:
        next_dir = data_dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    data_dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritance:r', '/grant:r', secrets_perm
                    ])

        data_dirs_explored.append(next_dir)

    for directory in reversed(data_dirs_explored):
        subprocess.run([
            'icacls', directory, '/inheritance:r', '/grant:r', datadir_perm
        ])

    # Remove current identity permissions
    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(str(nimbus_datadir))

    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', current_identity
                    ])

        dirs_explored.append(next_dir)

    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/remove:g', current_identity
        ])
    
    # Adding configuration to the Nimbus service
    nimbus_arguments = shlex.split(service_details['parameters']['AppParameters'], posix=False)

    # Fee recipient configuration (--suggested-fee-recipient)
    has_fee_recipient_config = False

    replaced_index = None
    replaced_arg = None
    replace_next = False

    for index, arg in enumerate(nimbus_arguments):
        if replace_next:
            replaced_index = index
            replaced_arg = f'{fee_recipient_address}'
            break
        elif arg.lower().startswith('--suggested-fee-recipient'):
            has_fee_recipient_config = True
            if '=' in arg:
                replaced_index = index
                replaced_arg = f'--suggested-fee-recipient={fee_recipient_address}'
                break
            else:
                replace_next = True

    if not has_fee_recipient_config:
        log.info('Adding fee recipient to Nimbus...')

        nimbus_arguments.append(f'--suggested-fee-recipient={fee_recipient_address}')
    else:
        log.warning('Nimbus was already configured with a fee recipient. We will try to update or make '
            'sure the configuration is correct.')
        
        if replaced_index is None or replaced_arg is None:
            log.error('No replacement found for fee recipient argument.')
            return False
        
        nimbus_arguments[replaced_index] = replaced_arg
    
    # Updating Nimbus service configuration
    if not set_service_param(nssm_binary, nimbus_service_name, 'AppParameters', nimbus_arguments):
        return False

    log.info('Starting Nimbus service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', nimbus_service_name
    ])

    delay = 30
    log.info(f'We are giving {delay} seconds for the Nimbus service to start properly.')
    time.sleep(delay)

    # Verify proper Nimbus service installation
    service_details = get_service_details(nssm_binary, nimbus_service_name)
    if not service_details:
        log.error('We could not find the Nimbus service we just created. '
            'We cannot continue.')
        return False

    log_path = base_directory.joinpath('var', 'log')
    nimbus_stdout_log_path = log_path.joinpath('nimbus-service-stdout.log')
    nimbus_stderr_log_path = log_path.joinpath('nimbus-service-stderr.log')

    if not (service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Nimbus service not running properly',
            text=(
f'''
The Nimbus service we just configured seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', nimbus_service_name])

        log.info(
f'''
To examine your Nimbus service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''
        )

        return False

    return public_keys

def install_lighthouse_validator(base_directory, network, keys, fee_recipient_address,
    mevboost_installed):
    # Import keystore(s) and configure the Lighthouse validator client (as part of a different service)
    # Returns a list of public keys when done

    base_directory = Path(base_directory)

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    lighthouse_datadir = base_directory.joinpath('var', 'lib', 'lighthouse')
    lighthouse_validators_dir = lighthouse_datadir.joinpath('validators')

    # Check if Lighthouse is already installed
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
        log.error('The Lighthouse binary is missing. We cannot continue.')
        return False

    # Check for existing service
    lighthouse_vc_service_exists = False
    lighthouse_vc_service_name = 'lighthousevalidator'

    service_details = get_service_details(nssm_binary, lighthouse_vc_service_name)

    if service_details is not None:
        lighthouse_vc_service_exists = True
    
    if lighthouse_vc_service_exists:
        result = button_dialog(
            title='Lighthouse validator client service found',
            text=(
f'''
The Lighthouse validator client service seems to have already been
created. Here are some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing the Lighthouse validator client service?
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

            subprocess.run([
                'icacls', str(lighthouse_validators_dir), '/grant:r', 'Everyone:(F)', '/t'
            ])

            if lighthouse_validators_dir.is_dir():                

                process_result = subprocess.run([
                    str(lighthouse_path), '--network', network, 'account', 'validator', 'list',
                    '--datadir', lighthouse_datadir
                    ], capture_output=True, text=True)
                if process_result.returncode == 0:
                    process_output = process_result.stdout
                    public_keys = re.findall(r'0x[0-9a-f]{96}', process_output)
                    public_keys = list(map(lambda x: x.strip(), public_keys))
                
                dirs_to_explore = []
                dirs_explored = []

                dirs_to_explore.append(str(lighthouse_validators_dir))
                
                while len(dirs_to_explore) > 0:
                    next_dir = dirs_to_explore.pop()

                    with os.scandir(next_dir) as it:
                        for entry in it:
                            if entry.is_dir():
                                dirs_to_explore.append(entry.path)
                            elif entry.is_file():
                                subprocess.run([
                                    'icacls', entry.path, '/remove:g', 'Everyone'
                                ])

                    dirs_explored.append(next_dir)
                
                for directory in reversed(dirs_explored):
                    subprocess.run([
                        'icacls', directory, '/remove:g', 'Everyone'
                    ])
            
            if len(public_keys) < 1:
                log.error('There is no keystore imported for the Lighthouse validator client to '
                    'perform its duties. We cannot continue.')
                return False
            
            return public_keys
        
        # User wants to proceed, make sure the Lighthouse service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', lighthouse_vc_service_name])

    passwordless_check = True
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

It will create a service that will automatically start the Lighthouse
validator client on reboot or if it crashes. The validator client will be
started, it will connect to your beacon node and it will be ready to
start validating once your validator(s) get activated.
'''     )),
            buttons=[
                ('Configure', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        # Check if lighthouse validators client directory already exists
        subprocess.run([
            'icacls', str(lighthouse_validators_dir), '/grant:r', 'Everyone:(F)', '/t'
        ])

        if lighthouse_validators_dir.is_dir():
            lighthouse_validators_dir_size = sizeof_fmt(get_dir_size(lighthouse_validators_dir))

            result = button_dialog(
                title='Lighthouse validator client data directory found',
                text=(
f'''
An existing lighthouse validator client data directory has been found.
Here are some details found:

Location: {lighthouse_validators_dir}
Size: {lighthouse_validators_dir_size}

Do you want to remove this directory first and start from nothing?
Removing this directory will also remove any key imported previously.
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
                shutil.rmtree(lighthouse_validators_dir)
        
        subprocess.run([
            'icacls', keys['validator_keys_path'], '/grant:r', 'Everyone:(F)', '/t'
        ])

        # Import keystore(s) if we have some
        if len(keys['keystore_paths']) > 0:
            subprocess.run([
                str(lighthouse_path), '--network', network, 'account', 'validator', 'import',
                '--directory', keys['validator_keys_path'], '--datadir', lighthouse_datadir])
        else:
            log.warning('No keystore files found to import. We\'ll guess they were already imported '
                'for now.')
            time.sleep(5)

        # Check for correct keystore(s) import
        public_keys = []

        process_result = subprocess.run([
            str(lighthouse_path), '--network', network, 'account', 'validator', 'list',
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

We cannot continue here without validator keys imported by the Lighthouse
validator client.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            return False

        # Check for imported keystore without a password

        vc_definitions_path = lighthouse_validators_dir.joinpath('validator_definitions.yml')

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
            shutil.rmtree(lighthouse_validators_dir)

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
    
    subprocess.run([
        'icacls', keys['validator_keys_path'], '/remove:g', 'Everyone', '/t'
    ])

    # Protect the imported keys and the validators directory
    system_identity = 'SYSTEM'
    datadir_perm = f'{system_identity}:(OI)(CI)(F)'
    secrets_perm = f'{system_identity}:(F)'
    
    data_dirs_to_explore = []
    data_dirs_explored = []

    data_dirs_to_explore.append(str(lighthouse_validators_dir))

    while len(data_dirs_to_explore) > 0:
        next_dir = data_dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    data_dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritance:r', '/grant:r', secrets_perm
                    ])
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', 'Everyone'
                    ])

        data_dirs_explored.append(next_dir)
    
    for directory in reversed(data_dirs_explored):
        subprocess.run([
            'icacls', directory, '/inheritance:r', '/grant:r', datadir_perm
        ])
        subprocess.run([
            'icacls', directory, '/remove:g', 'Everyone'
        ])
    
    log.info(
f'''
We found {len(public_keys)} key(s) imported into the lighthouse validator client.
'''
    )

    lighthouse_vc_arguments = LIGHTHOUSE_VC_ARGUMENTS[network]

    # Setup Lighthouse validator client service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    lighthouse_stdout_log_path = log_path.joinpath('lighthouse-validator-service-stdout.log')
    lighthouse_stderr_log_path = log_path.joinpath('lighthouse-validator-service-stderr.log')

    if lighthouse_stdout_log_path.is_file():
        lighthouse_stdout_log_path.unlink()
    if lighthouse_stderr_log_path.is_file():
        lighthouse_stderr_log_path.unlink()

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
        lighthouse_vc_arguments.append('--suggested-fee-recipient')
        lighthouse_vc_arguments.append(f'{fee_recipient_address}')
    
    if mevboost_installed:
        lighthouse_vc_arguments.append(f'--builder-proposals')
    
    lighthouse_vc_arguments.append('--datadir')
    lighthouse_vc_arguments.append(f'{lighthouse_datadir}')

    # Create Lighthouse validator client service
    parameters = {
        'DisplayName': LIGHTHOUSE_VC_SERVICE_DISPLAY_NAME[network],
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(lighthouse_stdout_log_path),
        'AppStderr': str(lighthouse_stderr_log_path),
        'AppStopMethodConsole': '1500'
    }

    if not create_service(nssm_binary, lighthouse_vc_service_name, str(lighthouse_path),
        lighthouse_vc_arguments, parameters):
        log.error('There was an issue creating the Lighthouse validator client service. '
            'We cannot continue.')
        return False

    log.info('Starting Lighthouse validator client service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', lighthouse_vc_service_name
    ])

    # Verify proper Lighthouse validator client installation
    delay = 6
    log.info(
f'''
We are giving the Lighthouse validator client {delay} seconds to start before
testing it.
'''
    )
    time.sleep(delay)
    
    # Verify proper Lighthouse validator client service installation
    service_details = get_service_details(nssm_binary, lighthouse_vc_service_name)
    if not service_details:
        log.error('We could not find the Lighthouse validator client service we just created. '
            'We cannot continue.')
        return False

    if not (service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Lighthouse validator client service not running properly',
            text=(
f'''
The Lighthouse validator client service we just created seems to have
issues. Here are some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Lighthouse validator client service cannot be
started properly. Make sure to check the logs and fix any issue found
there. You can see the logs in:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', lighthouse_vc_service_name])

        log.info(
f'''
To examine your Lighthouse validator client service logs, inspect the following files:

{lighthouse_stdout_log_path}
{lighthouse_stderr_log_path}
'''
        )

        return False

    return public_keys

def obtain_keys(base_directory, network, consensus_client):
    # Obtain validator keys for the selected network

    base_directory = Path(base_directory)

    # Check if there are keys already imported in our consensus client

    public_keys = []
    keys_location = UNKNOWN_VALUE
    generated_keys = {}

    # Check if there are keys already created
    keys_path = base_directory.joinpath('var', 'lib', 'eth', 'keys')

    # Ensure we currently have ACL permission to read from the keys path
    if keys_path.is_dir():
        subprocess.run([
            'icacls', str(keys_path), '/grant:r', 'Everyone:(F)', '/t'
        ])

    # Check if there are keys already created
    deposit_data_directory = base_directory.joinpath('var', 'lib', 'eth', 'deposit')
    target_deposit_data_path = deposit_data_directory.joinpath('deposit_data.json')

    generated_keys = search_for_generated_keys(keys_path)

    # Change ACL to protect keys directory
    if keys_path.is_dir():
        dirs_to_explore = []
        dirs_explored = []

        dirs_to_explore.append(str(keys_path))
        
        while len(dirs_to_explore) > 0:
            next_dir = dirs_to_explore.pop()

            with os.scandir(next_dir) as it:
                for entry in it:
                    if entry.is_dir():
                        dirs_to_explore.append(entry.path)
                    elif entry.is_file():
                        subprocess.run([
                            'icacls', entry.path, '/inheritancelevel:r', '/grant:r', 'SYSTEM:F'
                        ])
                        subprocess.run([
                            'icacls', entry.path, '/remove:g', 'Everyone'
                        ])

            dirs_explored.append(next_dir)
        
        for directory in reversed(dirs_explored):
            subprocess.run([
                'icacls', directory, '/inheritancelevel:r', '/grant:r', 'SYSTEM:F'
            ])
            subprocess.run([
                'icacls', directory, '/remove:g', 'Everyone'
            ])

    deposit_data_file = 'unknown'
    if target_deposit_data_path.is_file():
        deposit_data_file = target_deposit_data_path
    elif generated_keys['deposit_data_path'] is not None:
        deposit_data_file = generated_keys['deposit_data_path']
    
    if (
        len(generated_keys['keystore_paths']) > 0 or
        len(generated_keys['password_paths']) > 0
    ):
        result = button_dialog(
            title='Validator keys already created',
            text=(
f'''
It seems like validator keys have already been created. Here are some
details found:

Number of keystores: {len(generated_keys['keystore_paths'])}
Number of associated password files: {len(generated_keys['password_paths'])}
Deposit data file: {deposit_data_file}
Location: {keys_path}

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

    if consensus_client == CONSENSUS_CLIENT_NIMBUS:

        # Check if there are keys already imported into nimbus
        nimbus_datadir = base_directory.joinpath('var', 'lib', 'nimbus')
        keys_location = nimbus_datadir
        nimbus_validators_path = nimbus_datadir.joinpath('validators')

        # Ensure we currently have ACL permission to read from the keys path
        if nimbus_datadir.is_dir():

            subprocess.run([
                'icacls', str(nimbus_datadir), '/grant:r', 'Everyone:(F)', '/t'
            ])

            if nimbus_validators_path.is_dir():
                with os.scandir(nimbus_validators_path) as it:
                    for entry in it:
                        if entry.is_dir():
                            result = re.search(r'0x[0-9a-f]{96}', entry.name)
                            if result:
                                public_keys.append(result.group(0))

            dirs_to_explore = []
            dirs_explored = []

            dirs_to_explore.append(str(nimbus_datadir))
            
            while len(dirs_to_explore) > 0:
                next_dir = dirs_to_explore.pop()

                with os.scandir(next_dir) as it:
                    for entry in it:
                        if entry.is_dir():
                            dirs_to_explore.append(entry.path)
                        elif entry.is_file():
                            subprocess.run([
                                'icacls', entry.path, '/remove:g', 'Everyone'
                            ])

                dirs_explored.append(next_dir)
            
            for directory in reversed(dirs_explored):
                subprocess.run([
                    'icacls', directory, '/remove:g', 'Everyone'
                ])
    
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
            if keys_path.is_dir():
                subprocess.run([
                    'icacls', str(keys_path), '/grant:r', 'Everyone:(F)', '/t'
                ])
                shutil.rmtree(keys_path)
            keys_path.mkdir(parents=True, exist_ok=True)

            # Copy keys into keys_path
            with os.scandir(selected_keys_directory) as it:
                for entry in it:
                    if not entry.is_file():
                        continue

                    if not entry.name.endswith('.json'):
                        continue

                    if not (
                        entry.name.startswith('deposit_data') or
                        entry.name.startswith('keystore')):
                        continue

                    target_path = keys_path.joinpath(entry.name)
                    shutil.copyfile(entry.path, target_path)

            # Verify the generated keys
            imported_keys = search_for_generated_keys(keys_path)
            
            if len(imported_keys['keystore_paths']) == 0:
                log.warning(f'No key has been found while importing them from {keys_path}')
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
        eth2_deposit_cli_binary = base_directory.joinpath('bin', 'deposit.exe')

        eth2_deposit_found = False

        if eth2_deposit_cli_binary.is_file():
            try:
                process_result = subprocess.run([
                    str(eth2_deposit_cli_binary), '--help'
                    ], capture_output=True, text=True)
                eth2_deposit_found = True

                # TODO: Validate the output of deposit --help to make sure it's fine? Maybe?
                # process_output = process_result.stdout

            except FileNotFoundError:
                pass
        
        install_eth2_deposit_binary = True

        if eth2_deposit_found:
            result = button_dialog(
                title='staking-deposit-cli binary found',
                text=(
f'''
The staking-deposit-cli binary seems to have already been installed. Here
are some details found:

Location: {eth2_deposit_cli_binary}

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
            
            install_eth2_deposit_binary = (result == 2)

        if install_eth2_deposit_binary:
            # Getting latest staking-deposit-cli release files
            sdc_gh_release_url = GITHUB_REST_API_URL + SDC_LATEST_RELEASE
            headers = {'Accept': GITHUB_API_VERSION}
            try:
                response = httpx.get(sdc_gh_release_url, headers=headers, follow_redirects=True)
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

                if file_name.endswith('windows-amd64.zip'):
                    binary_asset = {
                        'file_name': file_name,
                        'file_url': file_url
                    }
                elif file_name.endswith('windows-amd64.sha256'):
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
            download_path = base_directory.joinpath('downloads')
            download_path.mkdir(parents=True, exist_ok=True)

            binary_path = Path(download_path, binary_asset['file_name'])
            binary_hash = hashlib.sha256()

            if binary_path.is_file():
                binary_path.unlink()

            try:
                with open(binary_path, 'wb') as binary_file:
                    log.info(f'Downloading staking-deposit-cli binary '
                        f'{binary_asset["file_name"]}...')
                    with httpx.stream('GET', binary_asset['file_url'],
                        follow_redirects=True) as http_stream:
                        if http_stream.status_code != 200:
                            log.error(f'Cannot download staking-deposit-cli binary from Github '
                                f'{binary_asset["file_url"]}.\nUnexpected status code '
                                f'{http_stream.status_code}')
                            return False
                        for data in http_stream.iter_bytes():
                            binary_file.write(data)
                            if checksum_asset is not None:
                                binary_hash.update(data)
            except httpx.RequestError as exception:
                log.error(f'Exception while downloading staking-deposit-cli binary from Github. '
                    f'Exception {exception}')
                return False

            if checksum_asset is not None:
                binary_hexdigest = binary_hash.hexdigest().lower()

                checksum_path = Path(download_path, checksum_asset['file_name'])

                if checksum_path.is_file():
                    checksum_path.unlink()

                try:
                    with open(checksum_path, 'wb') as signature_file:
                        log.info(f'Downloading staking-deposit-cli checksum '
                            f'{checksum_asset["file_name"]}...')
                        with httpx.stream('GET', checksum_asset['file_url'],
                            follow_redirects=True) as http_stream:
                            if http_stream.status_code != 200:
                                log.error(f'Cannot download staking-deposit-cli checksum from '
                                    f'Github {checksum_asset["file_url"]}.\nUnexpected status code '
                                    f'{http_stream.status_code}')
                                return False
                            for data in http_stream.iter_bytes():
                                signature_file.write(data)
                except httpx.RequestError as exception:
                    log.error(f'Exception while downloading staking-deposit-cli checksum from '
                        f'Github. Exception {exception}')
                    return False

                # Verify SHA256 signature
                log.info('Verifying staking-deposit-cli checksum...')
                checksum_value = ''
                with open(checksum_path, 'r', encoding='utf_16_le') as signature_file:
                    checksum_value = signature_file.read(1024).strip()
                
                # Remove download leftovers
                checksum_path.unlink()

                # Remove BOM
                if checksum_value.startswith('\ufeff'):
                    checksum_value = checksum_value[1:]
                checksum_value = checksum_value.lower()
                if binary_hexdigest != checksum_value:
                    log.error('SHA256 checksum failed on staking-deposit-cli binary from Github. '
                        f'Expected {checksum_value} but we got {binary_hexdigest}. We will stop '
                        f'here to protect you.')
                    return False
            
            # Unzip staking-deposit-cli archive
            bin_path = base_directory.joinpath('bin')
            bin_path.mkdir(parents=True, exist_ok=True)

            deposit_extracted_binary = None

            log.info(f'Extracting staking-deposit-cli binary {binary_asset["file_name"]}...')
            with ZipFile(binary_path, 'r') as zip_file:
                for name in zip_file.namelist():
                    if name.endswith('deposit.exe'):
                        deposit_extracted_binary = Path(zip_file.extract(name, download_path))
            
            # Remove download leftovers
            binary_path.unlink()

            if deposit_extracted_binary is None:
                log.error('The staking-deposit-cli binary was not found in the archive. '
                    'We cannot continue.')
                return False

            # Move deposit binary back into bin directory
            target_deposit_binary_path = bin_path.joinpath('deposit.exe')
            if target_deposit_binary_path.is_file():
                target_deposit_binary_path.unlink()
            
            deposit_extracted_binary.rename(target_deposit_binary_path)

            deposit_extracted_binary.parent.rmdir()

        # Clean potential leftover keys
        if keys_path.is_dir():
            subprocess.run([
                'icacls', str(keys_path), '/grant:r', 'Everyone:(F)', '/t'
            ])
            shutil.rmtree(keys_path)
        keys_path.mkdir(parents=True, exist_ok=True)
        
        command = [str(eth2_deposit_cli_binary), 'new-mnemonic', '--chain', network, '--folder',
            str(keys_path)]

        # Ask for withdrawal address
        withdrawal_address = select_withdrawal_address(log)
        if withdrawal_address is None or withdrawal_address is False:
            return False
        
        if withdrawal_address != '':
            command.extend(['--execution_address', withdrawal_address])

        # Launch staking-deposit-cli
        log.info('Generating keys with staking-deposit-cli binary...')
        subprocess.run(command, cwd=keys_path)

        # Clean up staking-deposit-cli binary
        eth2_deposit_cli_binary.unlink()

        # Reorganize generated files to move them up a directory
        validator_keys_path = keys_path.joinpath('validator_keys')
        if validator_keys_path.is_dir():
            with os.scandir(validator_keys_path) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    target_path = keys_path.joinpath(entry.name)
                    os.rename(entry.path, target_path)
            
            validator_keys_path.rmdir()

        # Verify the generated keys
        generated_keys = search_for_generated_keys(keys_path)
        
        if (
            generated_keys['deposit_data_path'] is None or
            len(generated_keys['keystore_paths']) == 0):
            log.warning('No key has been generated with the staking-deposit-cli tool.')
        else:
            actual_keys = generated_keys
            obtained_keys = True
    
    # Copy deposit data file outside of keys directory
    if deposit_data_directory.is_dir():
        shutil.rmtree(deposit_data_directory)
    deposit_data_directory.mkdir(parents=True, exist_ok=True)
    
    if actual_keys['deposit_data_path'] is not None:
        shutil.move(actual_keys['deposit_data_path'], target_deposit_data_path)

    if consensus_client == CONSENSUS_CLIENT_TEKU:

        # Generate password files
        keystore_password = input_dialog(
            title='Enter your keystore password',
            text=(
f'''
Please enter the password you used to create your keystore:

The password will be stored in a text file so that Teku can access your
validator keys when starting. Permissions will be changed so that only
the local system account can access the keys and the password file.

* Press the tab key to switch between the controls below
'''         ),
            password=True).run()

        if not keystore_password:
            return False

        with os.scandir(keys_path) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                if not entry.name.startswith('keystore'):
                    continue
                if not entry.name.endswith('.json'):
                    continue

                entry_path = Path(entry.path)
                target_file = keys_path.joinpath(entry_path.stem + '.txt')
                with open(target_file, 'w', encoding='utf8') as password_file:
                    password_file.write(keystore_password)

    actual_keys = search_for_generated_keys(keys_path)

    # Change ACL to protect keys directory
    dirs_to_explore = []
    dirs_explored = []

    dirs_to_explore.append(str(keys_path))
    
    while len(dirs_to_explore) > 0:
        next_dir = dirs_to_explore.pop()

        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.is_dir():
                    dirs_to_explore.append(entry.path)
                elif entry.is_file():
                    subprocess.run([
                        'icacls', entry.path, '/inheritancelevel:r', '/grant:r', 'SYSTEM:F'
                    ])
                    subprocess.run([
                        'icacls', entry.path, '/remove:g', 'Everyone'
                    ])

        dirs_explored.append(next_dir)
    
    for directory in reversed(dirs_explored):
        subprocess.run([
            'icacls', directory, '/inheritancelevel:r', '/grant:r', 'SYSTEM:F'
        ])
        subprocess.run([
            'icacls', directory, '/remove:g', 'Everyone'
        ])

    return actual_keys

def initiate_deposit(base_directory, network, keys, consensus_client):
    # Initiate and explain the deposit on launchpad

    base_directory = Path(base_directory)

    # Check if we have the deposit data file
    deposit_file_path = base_directory.joinpath('var', 'lib', 'eth', 'deposit',
        'deposit_data.json')
    if not deposit_file_path.is_file():
        log.warning('No deposit file found. We will assume that the deposit was already performed.')

        return True

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for syncing status before prompting for deposit
    local_bn_http_base = 'http://127.0.0.1:5052'

    stdout_log_path = UNKNOWN_VALUE
    stderr_log_path = UNKNOWN_VALUE

    bn_timeout = 5.0

    if consensus_client == CONSENSUS_CLIENT_TEKU:

        local_bn_http_base = 'http://127.0.0.1:5051'

        teku_service_name = 'teku'
        log_path = base_directory.joinpath('var', 'log')

        teku_stdout_log_path = log_path.joinpath('teku-service-stdout.log')
        teku_stderr_log_path = log_path.joinpath('teku-service-stderr.log')

        stdout_log_path = teku_stdout_log_path
        stderr_log_path = teku_stderr_log_path

        # Check if Teku service is still running
        service_details = get_service_details(nssm_binary, teku_service_name)
        if not service_details:
            log.error('We could not find the teku service we created. '
                'We cannot continue.')
            return False

        if not (
            service_details['status'] == WINDOWS_SERVICE_RUNNING):

            result = button_dialog(
                title='Teku service not running properly',
                text=(
f'''
The teku service we created seems to have issues. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the teku service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs in:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your teku service logs, inspect the following files:

{teku_stdout_log_path}
{teku_stderr_log_path}
'''
            )

            return False
    
    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:

        nimbus_service_name = 'nimbus'
        log_path = base_directory.joinpath('var', 'log')

        nimbus_stdout_log_path = log_path.joinpath('nimbus-service-stdout.log')
        nimbus_stderr_log_path = log_path.joinpath('nimbus-service-stderr.log')

        stdout_log_path = nimbus_stdout_log_path
        stderr_log_path = nimbus_stderr_log_path

        bn_timeout = 30

        # Check if Nimbus service is still running
        service_details = get_service_details(nssm_binary, nimbus_service_name)
        if not service_details:
            log.error('We could not find the Nimbus service we created. '
                'We cannot continue.')
            return False

        if not (
            service_details['status'] == WINDOWS_SERVICE_RUNNING):

            result = button_dialog(
                title='Nimbus service not running properly',
                text=(
f'''
The Nimbus service we created seems to have issues. Here are some details
found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your teku service logs, inspect the following files:

{nimbus_stdout_log_path}
{nimbus_stderr_log_path}
'''
            )

            return False
    
    elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        lighthouse_bn_service_name = 'lighthousebeacon'
        log_path = base_directory.joinpath('var', 'log')

        lighthouse_bn_stdout_log_path = log_path.joinpath('lighthouse-beacon-service-stdout.log')
        lighthouse_bn_stderr_log_path = log_path.joinpath('lighthouse-beacon-service-stderr.log')

        stdout_log_path = lighthouse_bn_stdout_log_path
        stderr_log_path = lighthouse_bn_stderr_log_path

        # Check if Lighthouse beacon node service is still running
        service_details = get_service_details(nssm_binary, lighthouse_bn_service_name)
        if not service_details:
            log.error('We could not find the Lighthouse beacon node service we created. '
                'We cannot continue.')
            return False

        if not (
            service_details['status'] == WINDOWS_SERVICE_RUNNING):

            result = button_dialog(
                title='Lighthouse beacon node service not running properly',
                text=(
f'''
The Lighthouse beacon node service we created seems to have issues. Here
are some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the Nimbus service cannot be started properly. Make
sure to check the logs and fix any issue found there. You can see the
logs in:

{lighthouse_bn_stdout_log_path}
{lighthouse_bn_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your teku service logs, inspect the following files:

{lighthouse_bn_stdout_log_path}
{lighthouse_bn_stderr_log_path}
'''
            )

            return False


    # Verify proper consensus installation and syncing
    bn_version_query = BN_VERSION_EP
    bn_query_url = local_bn_http_base + bn_version_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(bn_query_url, headers=headers, timeout=bn_timeout)
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

{stdout_log_path}
{stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your beacon node service logs, inspect the following files:

{stdout_log_path}
{stderr_log_path}
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

{stdout_log_path}
{stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your beacon node service logs, inspect the following files:

{stdout_log_path}
{stderr_log_path}
'''
        )

        return False
    
    is_fully_sync = False

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

            out_log_read_index = 0
            err_log_read_index = 0

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
                out_log_text = ''
                with open(stdout_log_path, 'r', encoding='utf8') as log_file:
                    log_file.seek(out_log_read_index)
                    out_log_text = log_file.read()
                    out_log_read_index = log_file.tell()
                
                err_log_text = ''
                with open(stderr_log_path, 'r', encoding='utf8') as log_file:
                    log_file.seek(err_log_read_index)
                    err_log_text = log_file.read()
                    err_log_read_index = log_file.tell()
                
                out_log_length = len(out_log_text)
                if out_log_length > 0:
                    log_text(out_log_text)

                err_log_length = len(err_log_text)
                if err_log_length > 0:
                    log_text(err_log_text)
                
                bn_syncing_query = BN_SYNCING_EP
                bn_query_url = local_bn_http_base + bn_syncing_query
                headers = {
                    'accept': 'application/json'
                }
                try:
                    response = httpx.get(bn_query_url, headers=headers, timeout=bn_timeout)
                except httpx.RequestError as exception:
                    log_text(f'Exception: {exception} while querying beacon node.')
                    continue

                if response.status_code != 200:
                    log_text(f'Status code: {response.status_code} while querying beacon node.')
                    continue
            
                response_json = response.json()
                syncing_json = response_json

                bn_peers_query = BN_PEERS_EP
                bn_query_url = local_bn_http_base + bn_peers_query
                headers = {
                    'accept': 'application/json'
                }
                try:
                    response = httpx.get(bn_query_url, headers=headers, timeout=bn_timeout)
                except httpx.RequestError as exception:
                    log_text(f'Exception: {exception} while querying beacon node.')
                    continue

                if response.status_code != 200:
                    log_text(f'Status code: {response.status_code} while querying beacon node.')
                    continue

                response_json = response.json()
                peers_json = response_json

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
                    peers_json and
                    'data' in peers_json and
                    type(peers_json['data']) is list
                    ):
                    for peer in peers_json['data']:
                        if 'state' not in peer:
                            continue
                        if peer['state'] == 'connected':
                            bn_connected_peers = bn_connected_peers + 1
                
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
'''         ).strip())

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
            # We could not get a proper result from the beacon node
            result = button_dialog(
                title='Beacon node beacon node syncing wait interrupted',
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

    log.info(
f'''
Here is your beacon node status before doing the deposit:

Syncing: {syncing_status['bn_is_syncing']} (Head slot: {syncing_status['bn_head_slot']}, Sync distance: {syncing_status['bn_sync_distance']})
Connected Peers: {syncing_status['bn_connected_peers']}
''' )

    launchpad_url = LAUNCHPAD_URLS[network]
    currency = NETWORK_CURRENCY[network]

    # TODO: Create an alternative way to easily obtain the deposit file with a simple HTTP server

    result = button_dialog(
        title='Deposit on the launchpad',
        text=(
f'''
This next step is to perform the 32 {currency} deposit(s) on the launchpad. In
order to do this deposit, you will need your deposit file which was created
during the key generation step. Your deposit file can be found in

{deposit_file_path}

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

    with open(deposit_file_path, 'r', encoding='utf8') as deposit_data_file:
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
key generation step. Your deposit file can be found in

{deposit_file_path}

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
key generation step. Your deposit file can be found in

{deposit_file_path}

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
        deposit_file_path.unlink()
    else:
        log.warning(
f'''
We could not verify that your deposit was completed. Make sure to keep a copy of your deposit file in
{deposit_file_path}
'''.strip())
    
    return True

def improve_time_sync():
    # Improve time sync

    result = button_dialog(
        title='Improve time synchronization',
        text=(
'''
Time synchronization is very important for a validator setup. Being out of
sync can lead to lower rewards and other undesirable results.

The default settings on a Windows 10 installation are poor for time sync.
This next step can significantly improve your time sync configuration for
your machine.

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
    
    # Stop Windows Time service
    subprocess.run([
        'net', 'stop', 'w32time'
    ])

    # Start Windows Time service
    subprocess.run([
        'net', 'start', 'w32time'
    ])

    # Configure Windows Time service to use 4 ntp.org servers
    subprocess.run([
        'w32tm', '/config', '/update', '/manualpeerlist:0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org'
    ])

    # Manually sync time
    subprocess.run([
        'w32tm', '/resync'
    ])

    # Set the Windows Time service to start automatically
    subprocess.run([
        'sc', 'config', 'w32time', 'start=auto'
    ])

    # Configure Windows Time service for High Accuracy as mentioned on
    # https://docs.microsoft.com/en-us/windows-server/networking/windows-time-service/configuring-systems-for-high-accuracy
    win32time_config_key = r'SYSTEM\CurrentControlSet\Services\W32Time\Config'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, win32time_config_key, 0, winreg.KEY_WRITE) as key:

        winreg.SetValueEx(key, 'MinPollInterval', 0, winreg.REG_DWORD, 6)
        winreg.SetValueEx(key, 'MaxPollInterval', 0, winreg.REG_DWORD, 10)
        winreg.SetValueEx(key, 'UpdateInterval', 0, winreg.REG_DWORD, 100)
        winreg.SetValueEx(key, 'FrequencyCorrectRate', 0, winreg.REG_DWORD, 2)

    ntpclient_key = r'SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ntpclient_key, 0, winreg.KEY_WRITE) as key:
    
        winreg.SetValueEx(key, 'SpecialPollInterval', 0, winreg.REG_DWORD, 2)
    
    # Restart the Windows Time service
    subprocess.run([
        'net', 'stop', 'w32time'
    ])
    subprocess.run([
        'net', 'start', 'w32time'
    ])

    return True

def disable_windows_updates():
    # Disable automatic download and installation of Windows updates

    result = button_dialog(
        title='Disable automatic Windows updates',
        text=(
'''
Automatic download and installation of Windows updates can impede the
proper functionning of a validator machine. A validator machine is expected
to run 24/7 to maximize your rewards. Installing regular Windows updates is
still strongly recommended to keep your machine secure, but moving this to
a manual process is recommended for a validator machine.

Going offline for a few minutes during a required reboot for Windows updates
should still be fine. By disabling automatic Windows updates you will have
greater control of when that happens.

Would you like to disable automatic Windows updates?
'''     ),
        buttons=[
            ('Disable', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if result == 2:
        return True

    if not result:
        return result

    # Based on Debloat-Windows-10 optimize windows update script
    # https://github.com/W4RH4WK/Debloat-Windows-10/blob/master/scripts/optimize-windows-update.ps1
    wuau_key = r'SOFTWARE\Wow6432Node\Policies\Microsoft\Windows\WindowsUpdate\AU'
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, wuau_key) as key:

        winreg.SetValueEx(key, 'NoAutoUpdate', 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, 'AUOptions', 0, winreg.REG_DWORD, 2)
        winreg.SetValueEx(key, 'ScheduledInstallDay', 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, 'ScheduledInstallTime', 0, winreg.REG_DWORD, 3)

    delivery_optimization_key = r'SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization'
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, delivery_optimization_key) as key:
    
        winreg.SetValueEx(key, 'DODownloadMode', 0, winreg.REG_DWORD, 0)

    return True

def adjust_power_plan():
    # Adjust the power plan and suggest the high performance one

    process_result = subprocess.run([
        'powercfg', '/l'
        ], capture_output=True, text=True)
    
    if process_result.returncode != 0:
        log.error('Unable to call powercfg to list power plans.')
        return False

    process_output = process_result.stdout

    active_plan = UNKNOWN_VALUE
    high_performance_plan_name = 'High performance'
    high_performance_plan_found = False
    current_plan_name = UNKNOWN_VALUE

    plans = {}

    for line in process_output.splitlines():
        match = re.search(r'Power Scheme GUID:\s*(?P<guid>\S+)\s*\((?P<name>[^\)]+)\)\s*(?P<active>\*?)', line)
        if match:
            is_active = match.group('active') == '*'
            guid = match.group('guid')
            name = match.group('name')
            if is_active:
                active_plan = guid
                current_plan_name = name
            plans[guid] = {
                'name': name,
                'active': is_active
            }

            if guid.lower() == WINDOWS_HIGH_PERFORMANCE_POWERPLAN_GUID.lower():
                high_performance_plan_name = name
                high_performance_plan_found = True
    
    if not high_performance_plan_found:
        log.warn('Could not find the high performance power plan. Skipping adjusting power plan.')
        return True

    if active_plan.lower() == WINDOWS_HIGH_PERFORMANCE_POWERPLAN_GUID.lower():
        log.info('Current power plan is already the high performance one. Skipping adjusting power plan.')
        return True

    result = button_dialog(
        title='Adjust power plan',
        text=(
f'''
You are currently using the {current_plan_name} power plan but we suggest
you switch to the {high_performance_plan_name} power plan.

Good performance is needed for a well functionning validator node. This
suggested power plan will give you a good baseline performance without
any sleeping issue with the default values.

Would you like to switch to this other power plan?
'''     ),
        buttons=[
            ('Switch', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if result == 2:
        return True

    if not result:
        return result
    
    log.info(f'Switching to {high_performance_plan_name} power plan...')

    process_result = subprocess.run(['powercfg', '/S', WINDOWS_HIGH_PERFORMANCE_POWERPLAN_GUID])
    if process_result.returncode != 0:
        log.error('Unable to change the current power plans.')
        return False
    
    return True

def install_monitoring(base_directory, consensus_client, execution_client):

    base_directory = Path(base_directory)

    result = button_dialog(
        title='Monitoring installation',
        text=(
f'''
This next step is optional but recommended. It will install Prometheus,
Grafana and Windows Exporter so you can easily monitor your machine's
resources, Geth, {consensus_client} and your validator(s).

It will download the official Prometheus binary distribution from GitHub,
it will download the official Grafana binary distribution their official
website and it will download the official Windows Exporter binary
distribution from GitHub.

Once installed locally, it will create a service that will automatically
start Prometheus, Grafana and Windows Exporter on reboot or if they crash.
'''     ),
        buttons=[
            ('Install', 1),
            ('Skip', 2),
            ('Quit', False)
        ]
    ).run()

    if result == 2:
        return True

    if not result:
        return result
    
    if not install_prometheus(base_directory, consensus_client, execution_client):
        return False
    
    if not install_windows_exporter(base_directory):
        return False
    
    if not install_grafana(base_directory, consensus_client, execution_client):
        return False
    
    # Show message on how to use monitoring
    result = button_dialog(
        title='Monitoring has been installed successfully',
        text=(
f'''
Everything needed for basic monitoring has been installed correctly.

You can access your Grafana server on: http://localhost:3000/

There is already an administrator user with the username: admin . You can
login with the default password: admin . On first login, you will be asked
to change your password.

Once logged in, you should be able to see various dashboards for Geth,
Teku and your system resources.
'''         ),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def install_prometheus(base_directory, consensus_client, execution_client):
    # Install Prometheus as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    prometheus_service_exists = False
    prometheus_service_name = 'prometheus'

    service_details = get_service_details(nssm_binary, prometheus_service_name)

    if service_details is not None:
        prometheus_service_exists = True
    
    if prometheus_service_exists:
        result = button_dialog(
            title='Prometheus service found',
            text=(
f'''
The prometheus service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing prometheus and its service?
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
        
        # User wants to proceed, make sure the prometheus service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', prometheus_service_name])

    # Check if prometheus is already installed
    prometheus_path = base_directory.joinpath('bin', 'prometheus')
    prometheus_binary_file = prometheus_path.joinpath('prometheus.exe')

    prometheus_found = False
    prometheus_version = 'unknown'

    if prometheus_binary_file.is_file():
        try:
            process_result = subprocess.run([
                str(prometheus_binary_file), '--version'
                ], capture_output=True, text=True)
            prometheus_found = True

            process_output = process_result.stdout
            result = re.search(r'prometheus, version (?P<version>[^ ]+)', process_output)
            if result:
                prometheus_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    install_prometheus_binary = True

    if prometheus_found:
        result = button_dialog(
            title='Prometheus binary distribution found',
            text=(
f'''
The prometheus binary distribution seems to have already been installed.
Here are some details found:

Version: {prometheus_version}
Location: {prometheus_path}

Do you want to skip installing the prometheus binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_prometheus_binary = (result == 2)
    
    if install_prometheus_binary:
        # Getting latest Prometheus release files
        prometheus_gh_release_url = GITHUB_REST_API_URL + PROMETHEUS_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(prometheus_gh_release_url, headers=headers,
                follow_redirects=True)
        except httpx.RequestError as exception:
            log.error(f'Cannot get latest Prometheus release from Github. '
                    f'Exception {exception}')
            return False

        if response.status_code != 200:
            log.error(f'Cannot get latest Prometheus release from Github. '
                    f'Status code {response.status_code}')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            log.error('No assets found in Github release for Prometheus.')
            return False
        
        binary_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('windows-amd64.zip'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
                break
        
        if binary_asset is None:
            log.error('No prometheus binary distribution found in Github release')
            return False
        
        # Downloading latest Prometheus binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = binary_asset['file_name']
        zip_url = binary_asset['file_url']

        prometheus_archive_path = download_path.joinpath(url_file_name)
        prometheus_archive_hash = hashlib.sha256()
        if prometheus_archive_path.is_file():
            prometheus_archive_path.unlink()

        try:
            with open(prometheus_archive_path, 'wb') as binary_file:
                log.info(f'Downloading prometheus archive {url_file_name}...')
                with httpx.stream('GET', zip_url, follow_redirects=True) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'Cannot download prometheus archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        prometheus_archive_hash.update(data)
        except httpx.RequestError as exception:
            log.error(f'Exception while downloading prometheus archive. Exception {exception}')
            return False
        
        # Unzip prometheus archive
        archive_members = None

        log.info(f'Extracting prometheus archive {url_file_name}...')
        with ZipFile(prometheus_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        prometheus_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            log.error('No files found in prometheus archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if prometheus_path.is_dir():
            shutil.rmtree(prometheus_path)
        prometheus_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, prometheus_path)
            
        # Make sure prometheus was installed properly
        prometheus_found = False
        if prometheus_binary_file.is_file():
            try:
                process_result = subprocess.run([
                    str(prometheus_binary_file), '--version'
                    ], capture_output=True, text=True)
                prometheus_found = True

                process_output = process_result.stdout
                result = re.search(r'prometheus, version (?P<version>[^ ]+)', process_output)
                if result:
                    prometheus_version = result.group('version').strip()

            except FileNotFoundError:
                pass
    
        if not prometheus_found:
            log.error(f'We could not find the prometheus binary distribution from the installed '
                f'archive in {prometheus_path}. We cannot continue.')
            return False
        else:
            log.info(f'Prometheus version {prometheus_version} installed.')

    # Check if prometheus directory already exists
    prometheus_datadir = base_directory.joinpath('var', 'lib', 'prometheus')
    if prometheus_datadir.is_dir():
        prometheus_datadir_size = sizeof_fmt(get_dir_size(prometheus_datadir))

        result = button_dialog(
            title='Prometheus data directory found',
            text=(
f'''
An existing prometheus data directory has been found. Here are some details
found:

Location: {prometheus_datadir}
Size: {prometheus_datadir_size}

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
            shutil.rmtree(prometheus_datadir)

    # Setup prometheus directory
    prometheus_datadir.mkdir(parents=True, exist_ok=True)

    # Setup prometheus config file
    prometheus_config_path = base_directory.joinpath('etc', 'prometheus')
    if not prometheus_config_path.is_dir():
        prometheus_config_path.mkdir(parents=True, exist_ok=True)
    
    prometheus_config_file = prometheus_config_path.joinpath('prometheus.yml')
    if prometheus_config_file.is_file():
        prometheus_config_file.unlink()
    
    prometheus_config_content = PROMETHEUS_CONFIG_WINDOWS

    prometheus_config_content = prometheus_config_content.format(
        scrape_configs=(
            EXECUTION_PROMETHEUS_CONFIG[execution_client] +
            '\n' +
            CONSENSUS_PROMETHEUS_CONFIG[consensus_client]))

    with open(str(prometheus_config_file), 'w', encoding='utf8') as config_file:
        config_file.write(prometheus_config_content)

    # Setup prometheus service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    prometheus_stdout_log_path = log_path.joinpath('prometheus-service-stdout.log')
    prometheus_stderr_log_path = log_path.joinpath('prometheus-service-stderr.log')

    if prometheus_stdout_log_path.is_file():
        prometheus_stdout_log_path.unlink()
    if prometheus_stderr_log_path.is_file():
        prometheus_stderr_log_path.unlink()

    prometheus_arguments = PROMETHEUS_ARGUMENTS
    prometheus_arguments.append('--config.file="' + str(prometheus_config_file) + '"')
    prometheus_arguments.append('--storage.tsdb.path="' + str(prometheus_datadir) + '"')

    parameters = {
        'DisplayName': PROMETHEUS_SERVICE_DISPLAY_NAME,
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(prometheus_stdout_log_path),
        'AppStderr': str(prometheus_stderr_log_path)
    }

    if not create_service(nssm_binary, prometheus_service_name, prometheus_binary_file,
        prometheus_arguments, parameters):
        log.error('There was an issue creating the prometheus service. We cannot continue.')
        return False

    log.info('Starting prometheus service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', prometheus_service_name
    ])

    delay = 15
    log.info(f'We are giving {delay} seconds for the prometheus service to start properly.')
    time.sleep(delay)

    # Verify proper Prometheus service installation
    service_details = get_service_details(nssm_binary, prometheus_service_name)
    if not service_details:
        log.error('We could not find the prometheus service we just created. '
            'We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Prometheus service not running properly',
            text=(
f'''
The prometheus service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the prometheus service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', prometheus_service_name])

        log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 10 seconds
    err_log_read_index = 0
    for i in range(2):
        err_log_text = ''
        with open(prometheus_stderr_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(err_log_read_index)
            err_log_text = log_file.read()
            err_log_read_index = log_file.tell()

        err_log_length = len(err_log_text)
        if err_log_length > 0:
            print(err_log_text, end='')

        time.sleep(5)

    # Do a simple query on Prometheus to see if it's working properly
    local_prometheus_query_url = 'http://localhost:9090/api/v1/query'
    params = {
        'query': 'promhttp_metric_handler_requests_total',
        'time': datetime.now().timestamp()
    }
    try:
        response = httpx.get(local_prometheus_query_url, params=params)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Prometheus',
            text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Exception: {exception}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Prometheus',
            text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Status code: {response.status_code}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        not response_json or
        'status' not in response_json or
        response_json['status'] != 'success'
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Prometheus',
            text=(
f'''
We received an unexpected response from the prometheus server. Here are
some details for this last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Response: {json.dumps(response_json)}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        params = {
            'query': 'promhttp_metric_handler_requests_total',
            'time': datetime.now().timestamp()
        }
        try:
            response = httpx.get(local_prometheus_query_url, params=params)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Prometheus',
                text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Exception: {exception}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Prometheus',
                text=(
f'''
We could not connect to prometheus server. Here are some details for this
last test we tried to perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Status code: {response.status_code}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
            )

            return False

        response_json = response.json()

    if (
        not response_json or
        'status' not in response_json or
        response_json['status'] != 'success'
    ):
        # We could not get a proper result from Prometheus after all those retries
        result = button_dialog(
            title='Unexpected response from Prometheus',
            text=(
f'''
After a few retries, we still received an unexpected response from the
prometheus server. Here are some details for this last test we tried to
perform:

URL: {local_prometheus_query_url}
Method: GET
Parameters: {json.dumps(params)}
Response: {json.dumps(response_json)}

We cannot proceed if the prometheus server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{prometheus_stderr_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your prometheus service logs, inspect the following file:

{prometheus_stderr_log_path}
'''
        )

        return False

    log.info(
f'''
Prometheus is installed and working properly.
''' )
    time.sleep(5)

    return True

def install_windows_exporter(base_directory):
    # Install Windows Exporter as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    we_service_exists = False
    we_service_name = 'windows_exporter'

    service_details = get_service_details(nssm_binary, we_service_name)

    if service_details is not None:
        we_service_exists = True
    
    if we_service_exists:
        result = button_dialog(
            title='Windows Exporter service found',
            text=(
f'''
The windows exporter service seems to have already been created. Here are
some details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}

Do you want to skip installing windows exporter and its service?
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
        
        # User wants to proceed, make sure the windows exporter service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', we_service_name])

    # Check if windows exporter is already installed
    we_found = False
    we_version = 'unknown'
    we_uninstall_command = None

    try:
        we_uninstall_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' + '\\' + WINDOWS_EXPORTER_GUID
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, we_uninstall_key) as key:
            we_found = True

            we_version = winreg.QueryValueEx(key, 'DisplayVersion')
            we_uninstall_command = winreg.QueryValueEx(key, 'UninstallString')
        
        if we_version:
            we_version = we_version[0]
        if we_uninstall_command:
            we_uninstall_command = we_uninstall_command[0]
        
    except OSError as exception:
        we_found = False
    
    install_we = True

    if we_found:
        result = button_dialog(
            title='Windows Exporter found',
            text=(
f'''
Windows exporter seems to have already been installed. Here are some
details found:

Version: {we_version}

Do you want to skip installing windows exporter?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_we = (result == 2)

    if install_we:
        # Uninstalling Windows Exporter first if found
        if we_found and we_uninstall_command is not None:
            log.info('Uninstalling Windows Exporter...')
            process_result = subprocess.run([
                'msiexec', '/x', WINDOWS_EXPORTER_GUID, '/qn'
            ])

            if process_result.returncode != 0:
                log.error(f'Unexpected return code from msiexec when uninstalling windows '
                    f'exporter. Return code {process_result.returncode}')
                return False
        
        # Getting latest Windows Exporter release files
        we_gh_release_url = GITHUB_REST_API_URL + WINDOWS_EXPORTER_LATEST_RELEASE
        headers = {'Accept': GITHUB_API_VERSION}
        try:
            response = httpx.get(we_gh_release_url, headers=headers, follow_redirects=True)
        except httpx.RequestError as exception:
            log.error(f'Cannot get latest Windows Exporter release from Github. '
                    f'Exception {exception}')
            return False

        if response.status_code != 200:
            log.error(f'Cannot get latest Windows Exporter release from Github. '
                    f'Status code {response.status_code}')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            log.error('No assets found in Github release for Windows Exporter.')
            return False
        
        binary_asset = None

        for asset in release_json['assets']:
            if 'name' not in asset:
                continue
            if 'browser_download_url' not in asset:
                continue
        
            file_name = asset['name']
            file_url = asset['browser_download_url']

            if file_name.endswith('amd64.msi'):
                binary_asset = {
                    'file_name': file_name,
                    'file_url': file_url
                }
                break
        
        if binary_asset is None:
            log.error('No windows exporter installer found in Github release')
            return False
        
        # Downloading latest Windows Exporter binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = binary_asset['file_name']
        installer_url = binary_asset['file_url']

        we_installer_path = download_path.joinpath(url_file_name)

        try:
            with open(we_installer_path, 'wb') as binary_file:
                log.info(f'Downloading windows exporter installer {url_file_name}...')
                with httpx.stream('GET', installer_url, follow_redirects=True) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'Cannot download windows exporter installer {installer_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            log.error(f'Exception while downloading windows exporter installer. '
                f'Exception {exception}')
            return False

        # Installing Windows Exporter
        log.info(f'Installing windows exporter using {url_file_name} ...')
        process_result = subprocess.run([
            'msiexec', '/i', str(we_installer_path), 'ENABLED_COLLECTORS=[defaults],time,process',
            'LISTEN_ADDR=127.0.0.1', 'LISTEN_PORT=9182', '/qn'
        ])

        # Remove download leftovers
        we_installer_path.unlink()

        if process_result.returncode != 0:
            log.error(f'Unexpected return code from msiexec when installing windows exporter. '
                f'Return code {process_result.returncode}')
            return False

    # Make sure the Windows Exporter service is started
    subprocess.run([
        str(nssm_binary), 'start', we_service_name
    ])

    delay = 15
    log.info(f'We are giving {delay} seconds for the windows exporter service to start properly.')
    time.sleep(delay)

    # Test Windows Exporter to see if we can read some metrics
    local_we_query_url = 'http://localhost:9182/metrics'
    try:
        response = httpx.get(local_we_query_url)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Windows Exporter',
            text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Exception: {exception}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Windows Exporter',
            text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False
    
    # Let's find the number of running processes as a test

    response_text = response.text
    match = re.search(r'windows_os_processes (?P<processes>\d+)', response_text)

    retry_index = 0
    retry_count = 5

    while (
        not match
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Windows Exporter',
            text=(
f'''
We received an unexpected response from the windows exporter server. Here
are some details for this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Missing line: windows_os_processes

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.get(local_we_query_url)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Windows Exporter',
                text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Exception: {exception}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Windows Exporter',
                text=(
f'''
We could not connect to windows exporter server. Here are some details for
this last test we tried to perform:

URL: {local_we_query_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
            )

            return False

        response_text = response.text
        match = re.search(r'windows_os_processes (?P<processes>\d+)', response_text)

    if (
        not match
    ):
        # We could not get a proper result from Windows Exporter after all those retries
        result = button_dialog(
            title='Unexpected response from Windows Exporter',
            text=(
f'''
After a few retries, we still received an unexpected response from the
windows exporter server. Here are some details for this last test we tried
to perform:

URL: {local_we_query_url}
Method: GET
Missing line: windows_os_processes

We cannot proceed if the windows exporter server is not responding
properly. Make sure to check the logs and fix any issue found there. You
can see the logs in the Event Viewer for Application with source
windows_exporter.
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your windows exporter service logs, inspect logs in the Event
Viewer for Application with source windows_exporter.
'''
        )

        return False

    log.info(
f'''
Windows Exporter is installed and working properly.
''' )
    time.sleep(5)

    return True

def install_grafana(base_directory, consensus_client, execution_client):
    # Install Grafana as a service

    nssm_binary = get_nssm_binary()
    if not nssm_binary:
        return False

    # Check for existing service
    grafana_service_exists = False
    grafana_service_name = 'grafana'

    service_details = get_service_details(nssm_binary, grafana_service_name)

    if service_details is not None:
        grafana_service_exists = True
    
    if grafana_service_exists:
        result = button_dialog(
            title='Grafana service found',
            text=(
f'''
The grafana service seems to have already been created. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

Do you want to skip installing grafana and its service?
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
        
        # User wants to proceed, make sure the grafana service is stopped first
        subprocess.run([
            str(nssm_binary), 'stop', grafana_service_name])

    # Check if grafana is already installed
    grafana_path = base_directory.joinpath('bin', 'grafana')
    grafana_bin_path = grafana_path.joinpath('bin')
    grafana_cli_binary_file = grafana_bin_path.joinpath('grafana-cli.exe')
    grafana_server_binary_file = grafana_bin_path.joinpath('grafana-server.exe')

    grafana_found = False
    grafana_version = UNKNOWN_VALUE

    if grafana_cli_binary_file.is_file():
        try:
            process_result = subprocess.run([
                str(grafana_cli_binary_file), '--version'
                ], capture_output=True, text=True)
            grafana_found = True

            process_output = process_result.stdout
            result = re.search(r'version (?P<version>[^ ]+)', process_output)
            if result:
                grafana_version = result.group('version').strip()

        except FileNotFoundError:
            pass
    
    install_grafana_binary = True

    if grafana_found:
        result = button_dialog(
            title='Grafana binary distribution found',
            text=(
f'''
The grafana binary distribution seems to have already been installed.
Here are some details found:

Version: {grafana_version}
Location: {grafana_path}

Do you want to skip installing the grafana binary distribution?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_grafana_binary = (result == 2)
    
    if install_grafana_binary:
        # Getting latest Grafana release

        retry_index = 0
        retry_count = 5
        retry_delay = 30

        base_timeout = 10.0
        timeout_retry_increment = 5.0

        response = None

        log.info('Getting Grafana download packages...')

        while (
            response is None or
            response.status_code != 200
        ) and retry_index < retry_count:
            try:
                timeout_delay = base_timeout + (timeout_retry_increment * retry_index)
                response = httpx.get(GRAFANA_DOWNLOAD_URL, params=GRAFANA_WINDOWS_PARAM,
                    timeout=timeout_delay, follow_redirects=True)
            except httpx.RequestError as exception:
                log.error(f'Cannot connect to Grafana download page. Exception {exception}.')
                    
                retry_index = retry_index + 1
                if retry_index < retry_count:
                    log.info(f'We will retry in {retry_delay} seconds.')
                    time.sleep(retry_delay)
                continue

            if response.status_code != 200:
                log.error(f'Grafana download page returned error code. '
                    f'Status code {response.status_code}')

                retry_index = retry_index + 1
                if retry_index < retry_count:
                    log.info(f'We will retry in {retry_delay} seconds.')
                    time.sleep(retry_delay)
                continue
        
        if response is None or response.status_code != 200:
            log.error(f'We could not get the Grafana download packages from the download page '
                f'after a few retries. We cannot continue.')
            return False
        
        response_text = response.text
        soup = BeautifulSoup(response_text, "html.parser")

        results = soup.find_all('div', class_='download-package')

        archive_sha256 = None
        archive_url = None

        for result in results:
            anchors = result.find_all('a')

            for anchor in anchors:
                href = anchor.attrs.get('href', None)
                if href and href.endswith('windows-amd64.zip'):
                    archive_url = href
            
            if archive_url is not None:
                sha_spans = result.find_all('span', class_='download-package__sha', limit=1)
                if sha_spans and len(sha_spans) > 0:
                    sha_text = sha_spans[0].text
                    match = re.search(r'SHA256:\s*(?P<sha256>\S+)', sha_text)
                    if match:
                        archive_sha256 = match.group('sha256').lower()
                break
        
        if archive_url is None:
            log.error('No grafana binary distribution found on grafana download page')
            return False
        
        # Downloading latest Grafana binary distribution archive
        download_path = base_directory.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        url_file_name = urlparse(archive_url).path.split('/')[-1]
        zip_url = archive_url

        grafana_archive_path = download_path.joinpath(url_file_name)
        grafana_archive_hash = hashlib.sha256()
        if grafana_archive_path.is_file():
            grafana_archive_path.unlink()

        try:
            with open(grafana_archive_path, 'wb') as binary_file:
                log.info(f'Downloading grafana archive {url_file_name}...')
                with httpx.stream('GET', zip_url, follow_redirects=True) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'Cannot download grafana archive {zip_url}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
                        grafana_archive_hash.update(data)
        except httpx.RequestError as exception:
            log.error(f'Exception while downloading grafana archive. Exception {exception}')
            return False
        
        # Verify checksum
        if archive_sha256 is not None:
            log.info('Verifying grafana archive checksum...')
            grafana_archive_hexdigest = grafana_archive_hash.hexdigest().lower()
            if grafana_archive_hexdigest != archive_sha256:
                log.error(f'Grafana archive checksum does not match. Expected {archive_sha256} '
                    f'but we got {grafana_archive_hexdigest}. We will stop here to protect you.')
                return False

        # Unzip grafana archive
        archive_members = None

        log.info(f'Extracting grafana archive {url_file_name}...')
        with ZipFile(grafana_archive_path, 'r') as zip_file:
            archive_members = zip_file.namelist()
            zip_file.extractall(download_path)
        
        # Remove download leftovers
        grafana_archive_path.unlink()

        if archive_members is None or len(archive_members) == 0:
            log.error('No files found in grafana archive. We cannot continue.')
            return False
        
        # Move all those extracted files into their final destination
        if grafana_path.is_dir():
            shutil.rmtree(grafana_path)
        grafana_path.mkdir(parents=True, exist_ok=True)

        archive_extracted_dir = download_path.joinpath(Path(archive_members[0]).parts[0])

        with os.scandir(archive_extracted_dir) as it:
            for diritem in it:
                shutil.move(diritem.path, grafana_path)
            
        # Make sure grafana was installed properly
        grafana_found = False
        grafana_version = UNKNOWN_VALUE

        if grafana_cli_binary_file.is_file():
            try:
                process_result = subprocess.run([
                    str(grafana_cli_binary_file), '--version'
                    ], capture_output=True, text=True)
                grafana_found = True

                process_output = process_result.stdout
                result = re.search(r'version (?P<version>[^ ]+)', process_output)
                if result:
                    grafana_version = result.group('version').strip()

            except FileNotFoundError:
                pass
    
        if not grafana_found:
            log.error(f'We could not find the grafana binary distribution from the installed '
                f'archive in {grafana_path}. We cannot continue.')
            return False
        else:
            log.info(f'Grafana version {grafana_version} installed.')

    # Check if config sample file exists
    grafana_source_config_file = grafana_path.joinpath('conf', 'sample.ini')
    if not grafana_source_config_file.is_file():
        log.error(f'We could not find the grafana config sample file from the installed '
            f'archive in {grafana_path}. We cannot continue.')
        return False

    # Check if grafana directory already exists
    grafana_datadir = base_directory.joinpath('var', 'lib', 'grafana')
    if grafana_datadir.is_dir():
        grafana_datadir_size = sizeof_fmt(get_dir_size(grafana_datadir))

        result = button_dialog(
            title='Grafana data directory found',
            text=(
f'''
An existing grafana data directory has been found. Here are some details
found:

Location: {grafana_datadir}
Size: {grafana_datadir_size}

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
            shutil.rmtree(grafana_datadir)

    # Setup grafana directory
    grafana_datadir.mkdir(parents=True, exist_ok=True)

    grafana_provisioningdir = grafana_datadir.joinpath('provisioning')
    grafana_provisioningdir.mkdir(parents=True, exist_ok=True)
    
    # Setup datasource provisioning for Prometheus
    grafana_datasourcedir = grafana_provisioningdir.joinpath('datasources')
    grafana_datasourcedir.mkdir(parents=True, exist_ok=True)

    prometheus_datasource_file = grafana_datasourcedir.joinpath('prometheus.yaml')
    with open(prometheus_datasource_file, 'w', encoding='utf8') as datasource_file:
        datasource_file.write(GRAFANA_PROMETHEUS_DATASOURCE)

    # Setup dashboard provisioning for Geth, Teku and Windows Exporter dashboards
    grafana_dashboardprovdir = grafana_provisioningdir.joinpath('dashboards')
    grafana_dashboardprovdir.mkdir(parents=True, exist_ok=True)

    grafana_dashboard_dir = grafana_datadir.joinpath('wizard-dashboards')
    grafana_dashboard_dir.mkdir(parents=True, exist_ok=True)

    grafana_dashboardprov_file = grafana_dashboardprovdir.joinpath('wizard.yaml')
    with open(grafana_dashboardprov_file, 'w', encoding='utf8') as dashboardprov_file:
        dashboardprov_file.write(
f'''
apiVersion: 1

providers:
  # <string> an unique provider name. Required
  - name: 'Wizard Dashboards'
    # <int> Org id. Default to 1
    orgId: 1
    # <string> name of the dashboard folder.
    folder: ''
    # <string> folder UID. will be automatically generated if not specified
    folderUid: ''
    # <string> provider type. Default to 'file'
    type: file
    # <bool> disable dashboard deletion
    disableDeletion: false
    # <int> how often Grafana will scan for changed dashboards
    updateIntervalSeconds: 60
    # <bool> allow updating provisioned dashboards from the UI
    allowUiUpdates: true
    options:
      # <string, required> path to dashboard files on disk. Required when using the 'file' type
      path: {grafana_dashboard_dir}
      # <bool> use folder names from filesystem to create folders in Grafana
      foldersFromFilesStructure: true
'''
        )
    
    if execution_client == EXECUTION_CLIENT_GETH:
        geth_dashboard_file = grafana_dashboard_dir.joinpath('geth.json')
        with open(geth_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(GETH_GRAFANA_DASHBOARD)
    elif execution_client == EXECUTION_CLIENT_NETHERMIND:
        nethermind_dashboard_file = grafana_dashboard_dir.joinpath('nethermind.json')
        with open(nethermind_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(NETHERMIND_GRAFANA_DASHBOARD)
    
    windows_system_dashboard_file = grafana_dashboard_dir.joinpath('windows-system.json')
    with open(windows_system_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(WINDOWS_SYSTEM_OVERVIEW_GRAFANA_DASHBOARD)
    
    windows_services_dashboard_file = grafana_dashboard_dir.joinpath('windows-services.json')
    with open(windows_services_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(WINDOWS_SERVICES_PROCESSES_GRAFANA_DASHBOARD)
    
    if consensus_client == CONSENSUS_CLIENT_TEKU:
        teku_dashboard_file = grafana_dashboard_dir.joinpath('teku.json')
        with open(teku_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(TEKU_GRAFANA_DASHBOARD)
    elif consensus_client == CONSENSUS_CLIENT_NIMBUS:
        nimbus_dashboard_file = grafana_dashboard_dir.joinpath('nimbus.json')
        with open(nimbus_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(NIMBUS_GRAFANA_DASHBOARD)
    elif consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:
        lighthouse_summary_dashboard_file = grafana_dashboard_dir.joinpath('lighthouse-summary.json')
        with open(lighthouse_summary_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(LIGHTHOUSE_SUMMARY_GRAFANA_DASHBOARD)
        lighthouse_vc_dashboard_file = grafana_dashboard_dir.joinpath('lighthouse-vc.json')
        with open(lighthouse_vc_dashboard_file, 'w', encoding='utf8') as dashboard_file:
            dashboard_file.write(LIGHTHOUSE_VC_GRAFANA_DASHBOARD)
    
    home_dashboard_file = grafana_dashboard_dir.joinpath('home.json')
    with open(home_dashboard_file, 'w', encoding='utf8') as dashboard_file:
        dashboard_file.write(HOME_GRAFANA_DASHBOARD)

    # Create grafana custom config file
    sample_config_content = None

    chunk_size = 1024 * 64

    with open(str(grafana_source_config_file), 'r', encoding='utf8') as sample_file:
        content_stream = io.StringIO()
        for chunk in iter(partial(sample_file.read, chunk_size), ''):
            content_stream.write(chunk)
        sample_config_content = content_stream.getvalue()
        content_stream.close()
    
    if sample_config_content is None or sample_config_content == '':
        log.error(f'We could not get the content of the grafana config sample file from the '
            f'installed archive in {grafana_path}. We cannot continue.')
        return False
    
    custom_config_content = sample_config_content
    custom_config_content = re.sub(
        r';http_addr =.*',
        'http_addr = 127.0.0.1',
        custom_config_content)
    custom_config_content = re.sub(
        r';data =.*',
        f'data = {re_repl_escape(str(grafana_datadir))}',
        custom_config_content)

    grafana_logsdir = grafana_datadir.joinpath('logs')
    grafana_logsdir.mkdir(parents=True, exist_ok=True)

    custom_config_content = re.sub(
        r';logs =.*',
        f'logs = {re_repl_escape(str(grafana_logsdir))}',
        custom_config_content)

    custom_config_content = re.sub(
        r';provisioning =.*',
        f'provisioning = {re_repl_escape(str(grafana_provisioningdir))}',
        custom_config_content)
    
    custom_config_content = re.sub(
        r';default_home_dashboard_path =.*',
        f'default_home_dashboard_path = {re_repl_escape(str(home_dashboard_file))}',
        custom_config_content)

    # Setup grafana custom config file
    grafana_config_path = base_directory.joinpath('etc', 'grafana')
    if not grafana_config_path.is_dir():
        grafana_config_path.mkdir(parents=True, exist_ok=True)
    
    grafana_config_file = grafana_config_path.joinpath('grafana.ini')
    if grafana_config_file.is_file():
        grafana_config_file.unlink()

    with open(str(grafana_config_file), 'w', encoding='utf8') as config_file:
        config_file.write(custom_config_content)

    # Install required plugins
    log.info('Installing required plugins for Grafana...')
    process_result = subprocess.run([
        str(grafana_cli_binary_file), 'plugins', 'install', 'flant-statusmap-panel'
    ], cwd=str(grafana_bin_path))

    # Setup grafana service
    log_path = base_directory.joinpath('var', 'log')
    log_path.mkdir(parents=True, exist_ok=True)

    grafana_stdout_log_path = log_path.joinpath('grafana-service-stdout.log')
    grafana_stderr_log_path = log_path.joinpath('grafana-service-stderr.log')

    if grafana_stdout_log_path.is_file():
        grafana_stdout_log_path.unlink()
    if grafana_stderr_log_path.is_file():
        grafana_stderr_log_path.unlink()

    grafana_arguments = [
        '-config', str(grafana_config_file)
    ]

    parameters = {
        'DisplayName': GRAFANA_SERVICE_DISPLAY_NAME,
        'AppRotateFiles': '1',
        'AppRotateSeconds': '86400',
        'AppRotateBytes': '10485760',
        'AppStdout': str(grafana_stdout_log_path),
        'AppStderr': str(grafana_stderr_log_path)
    }

    if not create_service(nssm_binary, grafana_service_name, grafana_server_binary_file,
        grafana_arguments, parameters):
        log.error('There was an issue creating the grafana service. We cannot continue.')
        return False

    log.info('Starting grafana service...')
    process_result = subprocess.run([
        str(nssm_binary), 'start', grafana_service_name
    ])

    delay = 15
    log.info(f'We are giving {delay} seconds for the grafana service to start properly.')
    time.sleep(delay)

    # Verify proper Grafana service installation
    service_details = get_service_details(nssm_binary, grafana_service_name)
    if not service_details:
        log.error('We could not find the grafana service we just created. We cannot continue.')
        return False

    if not (
        service_details['status'] == WINDOWS_SERVICE_RUNNING):

        result = button_dialog(
            title='Grafana service not running properly',
            text=(
f'''
The grafana service we just created seems to have issues. Here are some
details found:

Display name: {service_details['parameters'].get('DisplayName')}
Status: {service_details['status']}
Binary: {service_details['install']}
App parameters: {service_details['parameters'].get('AppParameters')}
App directory: {service_details['parameters'].get('AppDirectory')}

We cannot proceed if the grafana service cannot be started properly.
Make sure to check the logs and fix any issue found there. You can see the
logs in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        # Stop the service to prevent indefinite restart attempts
        subprocess.run([
            str(nssm_binary), 'stop', grafana_service_name])

        log.info(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False

    # Iterate over the logs and output them for around 10 seconds
    err_log_read_index = 0
    for i in range(2):
        err_log_text = ''
        with open(grafana_stdout_log_path, 'r', encoding='utf8') as log_file:
            log_file.seek(err_log_read_index)
            err_log_text = log_file.read()
            err_log_read_index = log_file.tell()

        err_log_length = len(err_log_text)
        if err_log_length > 0:
            print(err_log_text, end='')

        time.sleep(5)

    # Test if Grafana is working properly
    local_grafana_url = 'http://localhost:3000/login'
    try:
        response = httpx.get(local_grafana_url)
    except httpx.RequestError as exception:
        result = button_dialog(
            title='Cannot connect to Grafana',
            text=(
f'''
We could not connect to the grafana server. Here are some details for
this last test we tried to perform:

URL: {local_grafana_url}
Method: GET
Exception: {exception}

We cannot proceed if the grafana server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False

    if response.status_code != 200:
        result = button_dialog(
            title='Cannot connect to Grafana',
            text=(
f'''
We could not connect to the grafana server. Here are some details for
this last test we tried to perform:

URL: {local_grafana_url}
Method: GET
Status code: {response.status_code}

We cannot proceed if the grafana server is not responding properly. Make
sure to check the logs and fix any issue found there. You can see the logs
in:

{grafana_stdout_log_path}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your grafana service logs, inspect the following file:

{grafana_stdout_log_path}
'''
        )

        return False
    
    log.info(
f'''
Grafana is installed and working properly.
''' )
    time.sleep(5)
    
    return True

def re_repl_escape(value):
    return value.replace('\\', '\\\\')

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
    if num == 0:
        return 'Empty'
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)
