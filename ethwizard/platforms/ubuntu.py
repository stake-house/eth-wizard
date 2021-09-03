import os
import subprocess
import httpx
import hashlib
import shutil
import time
import humanize
import sys
import stat
import json
import re
import logging
import logging.handlers

from datetime import timedelta

from pathlib import Path

from ethwizard import __version__

from ethwizard.constants import *

from ethwizard.platforms.common import (
    select_network,
    select_custom_ports,
    select_eth1_fallbacks,
    progress_log_dialog,
    search_for_generated_keys,
    select_keys_directory,
    get_bc_validator_deposits,
    test_open_ports,
    show_whats_next,
    show_public_keys,
    Step,
    test_context_variable
)

from typing import Optional

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

log = logging.getLogger(__name__)

def installation_steps():

    def test_system_function(step, context, step_sequence):
        # Context variables
        want_to_test = CTX_WANT_TO_TEST
        disk_size_tested = CTX_DISK_SIZE_TESTED
        disk_speed_tested = CTX_DISK_SPEED_TESTED
        available_ram_tested = CTX_AVAILABLE_RAM_TESTED
        internet_speed_tested = CTX_INTERNET_SPEED_TESTED

        if want_to_test not in context:
            context[want_to_test] = show_test_overview()
            step_sequence.save_state(step.step_id, context)

        if not context[want_to_test]:
            # User asked to quit
            del context[want_to_test]
            step_sequence.save_state(step.step_id, context)

            quit_install()

        if context[want_to_test] == 1:
            if not context.get(disk_size_tested, False):
                if not test_disk_size():
                    # User asked to quit
                    quit_install()
                
                context[disk_size_tested] = True
                step_sequence.save_state(step.step_id, context)

            if not context.get(disk_speed_tested, False):
                if not test_disk_speed():
                    # User asked to quit
                    quit_install()
                
                context[disk_speed_tested] = True
                step_sequence.save_state(step.step_id, context)
            
            if not context.get(available_ram_tested, False):
                if not test_available_ram():
                    # User asked to quit
                    quit_install()
                
                context[available_ram_tested] = True
                step_sequence.save_state(step.step_id, context)

            if not context.get(internet_speed_tested, False):
                if not test_internet_speed():
                    # User asked to quit
                    quit_install()
                
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

            quit_install()
        
        return context
    
    select_network_step = Step(
        step_id=SELECT_NETWORK_STEP_ID,
        display_name='Network selection',
        exc_function=select_network_function
    )

    def select_custom_ports_function(step, context, step_sequence):
        # Context variables
        selected_ports = CTX_SELECTED_PORTS

        if selected_ports not in context:
            context[selected_ports] = {
                'eth1': DEFAULT_GETH_PORT,
                'eth2_bn': DEFAULT_LIGHTHOUSE_BN_PORT
            }
        
        context[selected_ports] = select_custom_ports(context[selected_ports])
        if not context[selected_ports]:
            # User asked to quit or error
            del context[selected_ports]
            step_sequence.save_state(step.step_id, context)

            quit_install()
        
        return context

    select_custom_ports_step = Step(
        step_id=SELECT_CUSTOM_PORTS_STEP_ID,
        display_name='Open ports configuration',
        exc_function=select_custom_ports_function
    )

    def install_geth_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_ports, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()

        if not install_geth(context[selected_network], context[selected_ports]):
            # User asked to quit or error
            quit_install()

        return context
    
    install_geth_step = Step(
        step_id=INSTALL_GETH_STEP_ID,
        display_name='Geth installation',
        exc_function=install_geth_function
    )

    def select_eth1_fallbacks_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_eth1_fallbacks = CTX_SELECTED_ETH1_FALLBACKS

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()

        if selected_eth1_fallbacks not in context:
            context[selected_eth1_fallbacks] = select_eth1_fallbacks(context[selected_network])
            step_sequence.save_state(step.step_id, context)

        if (
            type(context[selected_eth1_fallbacks]) is not list and
            not context[selected_eth1_fallbacks]):
            # User asked to quit
            del context[selected_eth1_fallbacks]
            step_sequence.save_state(step.step_id, context)

            quit_install()

        return context

    select_eth1_fallbacks_step = Step(
        step_id=SELECT_ETH1_FALLBACKS_STEP_ID,
        display_name='Adding Ethereum execution fallback nodes',
        exc_function=select_eth1_fallbacks_function
    )

    def install_lighthouse_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        selected_ports = CTX_SELECTED_PORTS
        selected_eth1_fallbacks = CTX_SELECTED_ETH1_FALLBACKS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, selected_ports, log) and
            test_context_variable(context, selected_eth1_fallbacks, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        if not install_lighthouse(context[selected_network], context[selected_eth1_fallbacks],
            context[selected_ports]):
            # User asked to quit or error
            quit_install()

        return context
    
    install_lighthouse_step = Step(
        step_id=INSTALL_LIGHTHOUSE_STEP_ID,
        display_name='Lighthouse installation',
        exc_function=install_lighthouse_function
    )

    def test_open_ports_function(step, context, step_sequence):
        # Context variables
        selected_ports = CTX_SELECTED_PORTS

        if not (
            test_context_variable(context, selected_ports, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        if not test_open_ports(context[selected_ports], log):
            # User asked to quit or error
            quit_install()

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

        if not (
            test_context_variable(context, selected_network, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        if obtained_keys not in context:
            context[obtained_keys] = obtain_keys(context[selected_network])
            step_sequence.save_state(step.step_id, context)

        if not context[obtained_keys]:
            # User asked to quit
            del context[obtained_keys]
            step_sequence.save_state(step.step_id, context)

            quit_install()

        return context

    obtain_keys_step = Step(
        step_id=OBTAIN_KEYS_STEP_ID,
        display_name='Importing or generating keys',
        exc_function=obtain_keys_function
    )

    def install_lighthouse_validator_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        if not install_lighthouse_validator(context[selected_network], context[obtained_keys]):
            # User asked to quit or error
            quit_install()

        return context
    
    install_lighthouse_validator_step = Step(
        step_id=INSTALL_LIGHTHOUSE_VALIDATOR_STEP_ID,
        display_name='Lighthouse validator client installation',
        exc_function=install_lighthouse_validator_function
    )

    def initiate_deposit_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        public_keys = CTX_PUBLIC_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        if public_keys not in context:
            context[public_keys] = initiate_deposit(context[selected_network],
                context[obtained_keys])
            step_sequence.save_state(step.step_id, context)

        if not context[public_keys]:
            # User asked to quit
            del context[public_keys]
            step_sequence.save_state(step.step_id, context)

            quit_install()

        return context

    initiate_deposit_step = Step(
        step_id=INITIATE_DEPOSIT_STEP_ID,
        display_name='Deposit on the launchpad',
        exc_function=initiate_deposit_function
    )

    def show_whats_next_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        public_keys = CTX_PUBLIC_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, public_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()

        show_whats_next(context[selected_network], context[obtained_keys], context[public_keys])

        return context
    
    show_whats_next_step = Step(
        step_id=SHOW_WHATS_NEXT_STEP_ID,
        display_name='Installation completed',
        exc_function=show_whats_next_function
    )

    def show_public_keys_function(step, context, step_sequence):
        # Context variables
        selected_network = CTX_SELECTED_NETWORK
        obtained_keys = CTX_OBTAINED_KEYS
        public_keys = CTX_PUBLIC_KEYS

        if not (
            test_context_variable(context, selected_network, log) and
            test_context_variable(context, obtained_keys, log) and
            test_context_variable(context, public_keys, log)
            ):
            # We are missing context variables, we cannot continue
            quit_install()
        
        show_public_keys(context[selected_network], context[obtained_keys], context[public_keys],
            log)

        return context
    
    show_public_keys_step = Step(
        step_id=SHOW_PUBLIC_KEYS_STEP_ID,
        display_name='Show public keys',
        exc_function=show_public_keys_function
    )

    return [
        test_system_step,
        select_network_step,
        select_custom_ports_step,
        install_geth_step,
        select_eth1_fallbacks_step,
        install_lighthouse_step,
        test_open_ports_step,
        obtain_keys_step,
        install_lighthouse_validator_step,
        # TODO: Check time synchronization and configure it if needed
        # TODO: Monitoring setup
        initiate_deposit_step,
        show_whats_next_step,
        show_public_keys_step
    ]

def save_state(step_id: str, context: dict) -> bool:
    # Save wizard state

    data_to_save = {
        'step': step_id,
        'context': context
    }

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        save_directory.mkdir(parents=True, exist_ok=True)
    save_file = save_directory.joinpath(STATE_FILE)

    with open(str(save_file), 'w', encoding='utf8') as output_file:
        json.dump(data_to_save, output_file)

    return True

def load_state() -> Optional[dict]:
    # Load wizard state

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        return None
    save_file = save_directory.joinpath(STATE_FILE)
    if not save_file.is_file():
        return None
    
    loaded_data = None

    try:
        with open(str(save_file), 'r', encoding='utf8') as input_file:
            loaded_data = json.load(input_file)
    except ValueError:
        return None
    
    return loaded_data

def quit_install():
    log.info(f'Quitting eth2-validator-wizard')
    quit()

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    log.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

def init_logging():
    # Initialize logging
    log.setLevel(logging.INFO)

    # Handle uncaught exception and log them
    sys.excepthook = handle_exception

    # Console handler to log into the console
    ch = logging.StreamHandler()
    log.addHandler(ch)

    # SysLog handler to log into syslog
    slh = logging.handlers.SysLogHandler(address='/dev/log')

    formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    slh.setFormatter(formatter)

    log.addHandler(slh)

    log.info(f'Starting eth2-validator-wizard version {__version__}')

def show_test_overview():
    # Show the overall tests to perform

    result = button_dialog(
        title='Testing your system',
        text=(
f'''
We can test your system to make sure it is fit for being a validator. Here
is the list of tests we will perform:

* Disk size (>= {MIN_AVAILABLE_DISK_SPACE_GB:.0f}GB of available space)
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

def test_disk_size():
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

    if not available_space_gb >= MIN_AVAILABLE_DISK_SPACE_GB:
        result = button_dialog(
            title=HTML('Disk size test <style bg="red" fg="black">failed</style>'),
            text=(HTML(
f'''
Your available space results seem to indicate that <style bg="red" fg="black">your disk size is
<b>smaller than</b> what would be required</style> to be a fully working validator. Here are
your results:

* Available space in /var/lib: {available_space_gb:.1f}GB (>= {MIN_AVAILABLE_DISK_SPACE_GB:.1f}GB)

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

* Available space in /var/lib: {available_space_gb:.1f}GB (>= {MIN_AVAILABLE_DISK_SPACE_GB:.1f}GB)
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

    script_path = Path(download_path, 'speedtest-cli')

    try:
        with open(script_path, 'wb') as binary_file:
            with httpx.stream('GET', SPEEDTEST_SCRIPT_URL) as http_stream:
                if http_stream.status_code != 200:
                    log.error('HTTP error while downloading speedtest-cli script. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        log.error(f'Exception while downloading speedtest-cli script. {exception}')
        return False
    
    # Run speedtest script
    log.info('Running speedtest to test internet speed...')

    process_result = subprocess.run([
        'python3', script_path, '--secure', '--json'
        ], capture_output=True, text=True)

    # Remove download leftovers
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

def install_geth(network, ports):
    # Install geth for the selected network

    # Check for existing systemd service
    geth_service_exists = False
    geth_service_name = 'geth.service'

    service_details = get_systemd_service_details(geth_service_name)

    if service_details['LoadState'] == 'loaded':
        geth_service_exists = True
    
    if geth_service_exists:
        result = button_dialog(
            title='Geth service found',
            text=(
f'''
The geth service seems to have already been created. Here are some details
found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

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

        process_result = subprocess.run([
            'dpkg', '-s', 'geth'
            ])
        if process_result.returncode == 0:
            # Geth package is installed
            geth_package_installed = True

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
The geth binary seems to have already been installed. Here are some
details found:

Version: {geth_version}
Location: {geth_location}
Installed from package: {geth_package_installed}
Installed from official Ethereum PPA: {installed_from_ppa}

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
        # Install Geth from PPA
        subprocess.run([
            'add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'geth'])
    
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
    
    # Setup Geth systemd service
    addparams = ''
    if ports['eth1'] != DEFAULT_GETH_PORT:
        addparams = f' --port {ports["eth1"]}'

    with open('/etc/systemd/system/' + geth_service_name, 'w') as service_file:
        service_file.write(GETH_SERVICE_DEFINITION[network].format(addparams=addparams))
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
The geth service we just created seems to have issues. Here are some
details found:

Description: {service_details['Description']}
States - Load: {service_details['LoadState']}, Active: {service_details['ActiveState']}, Sub: {service_details['SubState']}
UnitFilePreset: {service_details['UnitFilePreset']}
ExecStart: {service_details['ExecStart']}
ExecMainStartTimestamp: {service_details['ExecMainStartTimestamp']}
FragmentPath: {service_details['FragmentPath']}

We cannot proceed if the geth service cannot be started properly. Make sure
to check the logs and fix any issue found there. You can see the logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your geth service logs, type the following command:

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
We could not connect to geth HTTP-RPC server. Here are some details for
this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
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
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
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
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your geth service logs, type the following command:

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
                    '-u', geth_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '--after-cursor=' + journalctl_cursor, '-u', geth_service_name]
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
        run_callback=verifying_callback
    ).run()
    
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
logs and fix any issue found there. You can see the logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        log.info(
f'''
To examine your geth service logs, type the following command:

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

def get_systemd_service_details(service):
    # Return some systemd service details
    
    properties = ('Description', 'LoadState', 'ActiveState', 'ExecMainStartTimestamp',
        'FragmentPath', 'UnitFilePreset', 'SubState', 'ExecStart')

    process_result = subprocess.run([
        'systemctl', 'show', service,
        '--property=' + ','.join(properties)
        ], capture_output=True, text=True)
    process_output = process_result.stdout

    service_details = {}

    for sproperty in properties:
        result = re.search(re.escape(sproperty) + r'=(.*?)\n', process_output)
        if result:
            service_details[sproperty] = result.group(1).strip()
    
    for sproperty in properties:
        if sproperty not in service_details:
            service_details[sproperty] = 'unknown'

    return service_details

def install_lighthouse(network, eth1_fallbacks, ports):
    # Install Lighthouse for the selected network

    # Check for existing systemd service
    lighthouse_bn_service_exists = False
    lighthouse_bn_service_name = 'lighthousebeacon.service'

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
with good hardware and good internet.
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
            response = httpx.get(lighthouse_gh_release_url, headers=headers)
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
            log.error('Could not find binary or signature asset in Github release')
            return False
        
        # Downloading latest Lighthouse release files
        download_path = Path(Path.home(), 'ethwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])

        try:
            with open(binary_path, 'wb') as binary_file:
                with httpx.stream('GET', binary_asset['file_url']) as http_stream:
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
                with httpx.stream('GET', signature_asset['file_url']) as http_stream:
                    if http_stream.status_code != 200:
                        log.error(f'HTTP error while downloading Lighthouse signature from Github. '
                            f'Status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        signature_file.write(data)
        except httpx.RequestError as exception:
            log.error(f'Exception while downloading Lighthouse signature from Github. {exception}')
            return False

        # Install gpg using APT
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'gpg'])

        # Verify PGP signature

        retry_index = 0
        retry_count = 10

        key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
        command_line = ['gpg', '--keyserver', key_server, '--recv-keys',
            LIGHTHOUSE_PRIME_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                delay = 15
                log.warning(f'GPG failed to download the PGP key. We will wait {delay} seconds '
                    f'and try again.')
                time.sleep(delay)

                key_server = PGP_KEY_SERVERS[retry_index % len(PGP_KEY_SERVERS)]
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

    addparams = ''
    if ports['eth2_bn'] != DEFAULT_LIGHTHOUSE_BN_PORT:
        addparams = f' --port {ports["eth2_bn"]}'

    service_definition = service_definition.format(
        eth1endpoints=','.join(eth1_endpoints),
        addparams=addparams)

    with open('/etc/systemd/system/' + lighthouse_bn_service_name, 'w') as service_file:
        service_file.write(service_definition)
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', lighthouse_bn_service_name])
    subprocess.run([
        'systemctl', 'enable', lighthouse_bn_service_name])
    
    delay = 30
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
    local_lighthouse_bn_http_base = 'http://127.0.0.1:5052'
    
    lighthouse_bn_version_query = BN_VERSION_EP
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

        log.info(
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
                    '-u', lighthouse_bn_service_name]
            else:
                command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                    '--after-cursor=' + journalctl_cursor, '-u', lighthouse_bn_service_name]
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

def obtain_keys(network):
    # Obtain validator keys for the selected network

    # Check if there are keys already imported
    eth2_deposit_cli_path = Path(Path.home(), 'ethwizard', 'eth2depositcli')
    validator_keys_path = Path(eth2_deposit_cli_path, 'validator_keys')

    lighthouse_datadir = Path('/var/lib/lighthouse')

    process_result = subprocess.run([
        '/usr/local/bin/lighthouse', '--network', network, 'account', 'validator', 'list',
        '--datadir', lighthouse_datadir
        ], capture_output=True, text=True)
    if process_result.returncode == 0:
        process_output = process_result.stdout
        public_keys = re.findall(r'0x[0-9a-f]{96}\s', process_output)
        public_keys = list(map(lambda x: x.strip(), public_keys))
        
        if len(public_keys) > 0:
            # We already have keys imported

            result = button_dialog(
                title='Validator keys already imported',
                text=(
f'''
It seems like validator keys have already been imported. Here are some
details found:

Number of validators: {len(public_keys)}
Location: {lighthouse_datadir}

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
eth2.0-deposit-cli tool. You can download this tool from:

https://github.com/ethereum/eth2.0-deposit-cli

You can put the eth2.0-deposit-cli binary on a USB drive, generate your
keys on a different machine that is not connected to the internet, copy
your keys on the USB drive and import them here.

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
                    if not entry.is_file():
                        continue
                    target_path = validator_keys_path.joinpath(entry.name)
                    os.rename(entry.path, target_path)

            # Verify the generated keys
            imported_keys = search_for_generated_keys(validator_keys_path)
            
            if (
                imported_keys['deposit_data_path'] is None or
                len(imported_keys['keystore_paths']) == 0):
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

It will download the official eth2.0-deposit-cli binary from GitHub,
verify its SHA256 checksum, extract it and start it.

The eth2.0-deposit-cli tool is executed in an interactive way where you
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
    
        # Check if eth2.0-deposit-cli is already installed
        eth2_deposit_cli_binary = Path(eth2_deposit_cli_path, 'deposit')

        eth2_deposit_found = False

        if eth2_deposit_cli_binary.exists() and eth2_deposit_cli_binary.is_file():
            try:
                process_result = subprocess.run([
                    eth2_deposit_cli_binary, '--help'
                    ], capture_output=True, text=True)
                eth2_deposit_found = True

                # TODO: Validate the output of deposit --help to make sure it's fine? Maybe?
                # process_output = process_result.stdout

            except FileNotFoundError:
                pass
        
        install_eth2_deposit_binary = True

        if eth2_deposit_found:
            result = button_dialog(
                title='eth2.0-deposit-cli binary found',
                text=(
f'''
The eth2.0-deposit-cli binary seems to have already been installed. Here
are some details found:

Location: {eth2_deposit_cli_binary}

Do you want to skip installing the eth2.0-deposit-cli binary?
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
            # Getting latest eth2.0-deposit-cli release files
            eth2_cli_gh_release_url = GITHUB_REST_API_URL + ETH2_DEPOSIT_CLI_LATEST_RELEASE
            headers = {'Accept': GITHUB_API_VERSION}
            try:
                response = httpx.get(eth2_cli_gh_release_url, headers=headers)
            except httpx.RequestError as exception:
                log.error(f'Cannot get latest eth2.0-deposit-cli release from Github. '
                    f'Exception {exception}')
                return False

            if response.status_code != 200:
                log.error(f'Cannot get latest eth2.0-deposit-cli release from Github. '
                    f'Status code {response.status_code}')
                return False
            
            release_json = response.json()

            if 'assets' not in release_json:
                log.error('No assets in Github release for eth2.0-deposit-cli.')
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
                log.error('No eth2.0-deposit-cli binary found in Github release')
                return False
            
            checksum_path = None

            if checksum_asset is None:
                log.warning('No eth2.0-deposit-cli checksum found in Github release')
            
            # Downloading latest eth2.0-deposit-cli release files
            download_path = Path(Path.home(), 'ethwizard', 'downloads')
            download_path.mkdir(parents=True, exist_ok=True)

            binary_path = Path(download_path, binary_asset['file_name'])
            binary_hash = hashlib.sha256()

            try:
                with open(binary_path, 'wb') as binary_file:
                    with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                        if http_stream.status_code != 200:
                            log.error(f'HTTP error while downloading eth2.0-deposit-cli binary '
                                f'from Github. Status code {http_stream.status_code}')
                            return False
                        for data in http_stream.iter_bytes():
                            binary_file.write(data)
                            if checksum_asset is not None:
                                binary_hash.update(data)
            except httpx.RequestError as exception:
                log.error(f'Exception while downloading eth2.0-deposit-cli binary from '
                    f'Github. {exception}')
                return False

            if checksum_asset is not None:
                binary_hexdigest = binary_hash.hexdigest().lower()

                checksum_path = Path(download_path, checksum_asset['file_name'])

                try:
                    with open(checksum_path, 'wb') as signature_file:
                        with httpx.stream('GET', checksum_asset['file_url']) as http_stream:
                            if http_stream.status_code != 200:
                                log.error(f'HTTP error while downloading eth2.0-deposit-cli '
                                    f'checksum from Github. Status code {http_stream.status_code}')
                                return False
                            for data in http_stream.iter_bytes():
                                signature_file.write(data)
                except httpx.RequestError as exception:
                    log.error(f'Exception while downloading eth2.0-deposit-cli checksum from '
                    f'Github. {exception}')
                    return False

                # Verify SHA256 signature
                with open(checksum_path, 'r') as checksum_file:
                    checksum = checksum_file.read(1024).strip().lower()
                    if binary_hexdigest != checksum:
                        # SHA256 checksum failed
                        log.error(f'SHA256 checksum failed on eth2.0-deposit-cli binary from '
                            f'Github. Expected {checksum} but we got {binary_hexdigest}. We will '
                            f'stop here to protect you')
                        return False
            
            # Extracting the eth2.0-deposit-cli binary archive
            eth2_deposit_cli_path.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                'tar', 'xvf', binary_path, '--strip-components', '2', '--directory',
                eth2_deposit_cli_path])
            
            # Remove download leftovers
            binary_path.unlink()
            if checksum_path is not None:
                checksum_path.unlink()

        # Clean potential leftover keys
        if validator_keys_path.is_dir():
            shutil.rmtree(validator_keys_path)
        
        # Launch eth2.0-deposit-cli
        subprocess.run([
            eth2_deposit_cli_binary, 'new-mnemonic', '--chain', network],
            cwd=eth2_deposit_cli_path)

        # Clean up eth2.0-deposit-cli binary
        eth2_deposit_cli_binary.unlink()

        # Verify the generated keys
        generated_keys = search_for_generated_keys(validator_keys_path)
        
        if (
            generated_keys['deposit_data_path'] is None or
            len(generated_keys['keystore_paths']) == 0):
            log.warning('No key has been generated with the eth2.0-deposit-cli tool.')
        else:
            actual_keys = generated_keys
            obtained_keys = True

    return actual_keys

def install_lighthouse_validator(network, keys):
    # Import keystore(s) and configure the Lighthouse validator client

    # Check for existing systemd service
    lighthouse_vc_service_exists = False
    lighthouse_vc_service_name = 'lighthousevalidator.service'

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
            return True
        
        # User wants to proceed, make sure the lighthouse validator service is stopped first
        subprocess.run([
            'systemctl', 'stop', lighthouse_vc_service_name])

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
    lighthouse_datadir_vc = Path('/var/lib/lighthouse/validators')
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
    lighthouse_datadir = Path('/var/lib/lighthouse')

    if len(keys['keystore_paths']) > 0:
        subprocess.run([
            '/usr/local/bin/lighthouse', '--network', network, 'account', 'validator', 'import',
            '--directory', keys['validator_keys_path'], '--datadir', lighthouse_datadir])
    else:
        log.warning('No keystore files found to import. We\'ll guess they were already imported '
            'for now.')
        time.sleep(5)

    # Check for correct keystore(s) import
    public_keys = []

    process_result = subprocess.run([
        '/usr/local/bin/lighthouse', '--network', network, 'account', 'validator', 'list',
        '--datadir', lighthouse_datadir
        ], capture_output=True, text=True)
    if process_result.returncode == 0:
        process_output = process_result.stdout
        public_keys = re.findall(r'0x[0-9a-f]{96}\s', process_output)
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

    # Setup Lighthouse validator client systemd service
    with open('/etc/systemd/system/' + lighthouse_vc_service_name, 'w') as service_file:
        service_file.write(LIGHTHOUSE_VC_SERVICE_DEFINITION[network])
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
            'journalctl', '-fu', lighthouse_vc_service_name
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

    return True

def initiate_deposit(network, keys):
    # Initiate and explain the deposit on launchpad

    # Check for syncing status before prompting for deposit

    # Response example from Lighthouse Beacon Node /eth​/v1​/node​/syncing API

    # {"data":{"is_syncing":true,"head_slot":"23040","sync_distance":"1159516"}}
    # {"data":{"is_syncing":true,"head_slot":"29760","sync_distance":"1152846"}}
    # {"data":{"is_syncing":true,"head_slot":"38656","sync_distance":"1144017"}}
    # {"data":{"is_syncing":false,"head_slot":"1182703","sync_distance":"0"}}

    # Check if the Lighthouse beacon node service is still running
    lighthouse_bn_service_name = 'lighthousebeacon.service'

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

    # Verify proper Lighthouse beacon node installation and syncing
    local_lighthouse_bn_http_base = 'http://127.0.0.1:5052'
    
    lighthouse_bn_version_query = BN_VERSION_EP
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

        log.info(
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

        log.info(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    is_fully_sync = False

    while not is_fully_sync:

        # Verify proper Lighthouse beacon node syncing
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
                        '-u', lighthouse_bn_service_name]
                else:
                    command = ['journalctl', '--no-pager', '--show-cursor', '-q',
                        '--after-cursor=' + journalctl_cursor, '-u', lighthouse_bn_service_name]
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
            response = httpx.get(beaconcha_in_queue_query_url, headers=headers)

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
            title='Verifying Lighthouse beacon node syncing status',
            text=(HTML(
f'''
It is a good idea to wait for your beacon node to be in sync before doing
the deposit so you do not miss any reward. Activating a validator after the
deposit usually take around 15 hours unless the join queue is longer. There
is currently {network_queue_info} for the <b>{network.capitalize()}</b>
Ethereum network.
'''         )),
            status_text=(
'''
Syncing: Unknown (Head slot: Unknown, Sync distance: Unknown)
Connected Peers: Unknown
'''
            ).strip(),
            quit_text='Proceed',
            run_callback=verifying_callback
        ).run()
        
        if not result:
            log.warning('Lighthouse beacon node syncing wait was cancelled.')
            return False
        
        syncing_status = result

        if not result['bn_is_fully_sync']:
            # We could not get a proper result from Lighthouse
            result = button_dialog(
                title='Lighthouse beacon node syncing wait interrupted',
                text=(HTML(
f'''
We were interrupted before we could confirm the lighthouse beacon node
was in sync. Here are some results for the last tests we performed:

Syncing: {result['bn_is_syncing']} (Head slot: {result['bn_head_slot']}, Sync distance: {result['bn_sync_distance']})
Connected Peers: {result['bn_connected_peers']}

<style bg="red" fg="black"><b>WARNING</b></style>: Proceeding with the deposit without having a beacon node fully in
sync has the potential to make you miss some reward between the time your
validator is activated and your beacon node is fully in sync.

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
        log.error('Unable to get validator(s) deposits from beaconcha.in')
        return False

    while len(validator_deposits) == 0:
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
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys, log)

        if type(validator_deposits) is not list and not validator_deposits:
            log.error('Unable to get validator(s) deposits from beaconcha.in')
            return False
    
    # Check if all the deposit(s) were done for each validator
    while len(validator_deposits) < len(public_keys):

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
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys, log)

        if type(validator_deposits) is not list and not validator_deposits:
            log.error('Unable to get validator(s) deposits from beaconcha.in')
            return False

    # Clean up deposit data file
    deposit_file_copy_path.unlink()
    os.unlink(keys['deposit_data_path'])
    
    return public_keys
