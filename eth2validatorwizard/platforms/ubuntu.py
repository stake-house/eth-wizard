import os
import subprocess
import httpx
import hashlib
import shutil
import time
import stat
import json
import re

from pathlib import Path

from eth2validatorwizard.constants import *

from eth2validatorwizard.platforms.common import (
    select_network,
    select_custom_ports,
    select_eth1_fallbacks,
    search_for_generated_keys,
    select_keys_directory,
    get_bc_validator_deposits,
    test_open_ports,
    show_whats_next,
    show_public_keys
)

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

def installation_steps():

    want_to_test = show_test_overview()
    if not want_to_test:
        # User asked to quit
        quit()

    if want_to_test == 1:
        if not test_disk_size():
            # User asked to quit
            quit()
        if not test_disk_speed():
            # User asked to quit
            quit()
        if not test_available_ram():
            # User asked to quit
            quit()
        if not test_internet_speed():
            # User asked to quit
            quit()

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit()
    
    selected_ports = {
        'eth1': DEFAULT_GETH_PORT,
        'eth2_bn': DEFAULT_LIGHTHOUSE_BN_PORT
    }

    selected_ports = select_custom_ports(selected_ports)
    if not selected_ports:
        # User asked to quit or error
        quit()

    if not install_geth(selected_network, selected_ports):
        # User asked to quit or error
        quit()

    selected_eth1_fallbacks = select_eth1_fallbacks(selected_network)
    if type(selected_eth1_fallbacks) is not list and not selected_eth1_fallbacks:
        # User asked to quit
        quit()

    if not install_lighthouse(selected_network, selected_eth1_fallbacks, selected_ports):
        # User asked to quit or error
        quit()

    if not test_open_ports(selected_ports):
        # User asked to quit or error
        quit()

    obtained_keys = obtain_keys(selected_network)
    if not obtained_keys:
        # User asked to quit or error
        quit()

    if not install_lighthouse_validator(selected_network, obtained_keys):
        # User asked to quit or error
        quit()

    # TODO: Check time synchronization and configure it if needed

    # TODO: Monitoring setup

    public_keys = initiate_deposit(selected_network, obtained_keys)
    if not public_keys:
        # User asked to quit or error
        quit()

    show_whats_next(selected_network, obtained_keys, public_keys)

    show_public_keys(selected_network, obtained_keys, public_keys)

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

    process_result = subprocess.run([
        'df', '-h', '--output=avail', '-B1MB', '/var/lib'
        ], capture_output=True, text=True)
    
    if process_result.returncode != 0:
        print(f'Unable to test disk size. Return code {process_result.returncode}')
        print(f'{process_result.stdout}\n{process_result.stderr}')
        return False
    
    process_output = process_result.stdout
    result = re.search(r'(\d+)', process_output)
    available_space_gb = None
    if result:
        available_space_gb = int(result.group(1)) / 1000.0

    if available_space_gb is None:
        print('Unable to test disk size. Unexpected output from df command. {process_output}')
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
    print('Installing fio...')

    subprocess.run([
        'apt', '-y', 'update'])
    subprocess.run([
        'apt', '-y', 'install', 'fio'])
    
    # Run fio test
    fio_path = Path(Path.home(), 'eth2validatorwizard', 'fio')
    fio_path.mkdir(parents=True, exist_ok=True)

    fio_target_filename = 'random_read_write.fio'
    fio_output_filename = 'fio.out'

    fio_target_path = Path(fio_path, fio_target_filename)
    fio_output_path = Path(fio_path, fio_output_filename)

    print('Executing fio...')

    process_result = subprocess.run([
        'fio', '--randrepeat=1', '--ioengine=libaio', '--direct=1', '--gtod_reduce=1',
        '--name=test', '--filename=' + fio_target_filename, '--bs=4k', '--iodepth=64',
        '--size=4G', '--readwrite=randrw', '--rwmixread=75', '--output=' + fio_output_filename,
        '--output-format=json'
        ], cwd=fio_path)

    if process_result.returncode != 0:
        print(f'Error while running fio disk test. Return code {process_result.returncode}')
        return False
    
    # Remove test file
    fio_target_path.unlink()

    results_json = None

    with open(fio_output_path, 'r') as output_file:
        results_json = json.loads(output_file.read(8 * 1024 * 20))

    # Remove test results
    fio_output_path.unlink()

    if results_json is None:
        print('Could not read the results from fio output file.')
        return False
    
    if 'jobs' not in results_json or type(results_json['jobs']) is not list:
        print('Unexpected structure from fio output file. No jobs list.')
        return False
    
    jobs = results_json['jobs']

    # Find our test job and the results
    test_job = None
    for job in jobs:
        if 'jobname' not in job:
            print('Unexpected structure from fio output file. No jobname in a job.')
            return False
        jobname = job['jobname']
        if jobname == 'test':
            test_job = job
            break

    if test_job is None:
        print('Unable to find our test job in fio output file.')
        return False
    
    if not (
        'read' in test_job and
        'iops' in test_job['read'] and
        type(test_job['read']['iops']) is float and
        'write' in test_job and
        'iops' in test_job['write'] and
        type(test_job['write']['iops']) is float):
        print('Unexpected structure from fio output file. No read or write iops.')
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
    print('Downloading speedtest-cli script...')
    download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    script_path = Path(download_path, 'speedtest-cli')

    try:
        with open(script_path, 'wb') as binary_file:
            with httpx.stream('GET', SPEEDTEST_SCRIPT_URL) as http_stream:
                if http_stream.status_code != 200:
                    print('HTTP error while downloading speedtest-cli script. '
                        f'Status code {http_stream.status_code}')
                    return False
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
    except httpx.RequestError as exception:
        print(f'Exception while downloading speedtest-cli script. {exception}')
        return False
    
    # Run speedtest script
    print('Running speedtest...')

    process_result = subprocess.run([
        'python3', script_path, '--secure', '--json'
        ], capture_output=True, text=True)

    # Remove download leftovers
    script_path.unlink()

    if process_result.returncode != 0:
        print(f'Unable to run speedtest script. Return code {process_result.returncode}')
        print(f'{process_result.stdout}\n{process_result.stderr}')
        return False

    process_output = process_result.stdout
    speedtest_results = json.loads(process_output)

    if (
        'download' not in speedtest_results or
        type(speedtest_results['download']) is not float or
        'upload' not in speedtest_results or
        type(speedtest_results['upload']) is not float
    ):
        print(f'Unexpected response from speedtest. \n {speedtest_results}')
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

    process_result = subprocess.run([
        'grep', 'MemTotal', '/proc/meminfo'
        ], capture_output=True, text=True)
    
    if process_result.returncode != 0:
        print(f'Unable to get available total RAM. Return code {process_result.returncode}')
        print(f'{process_result.stdout}\n{process_result.stderr}')
        return False
    
    process_output = process_result.stdout

    total_available_ram_gb = 0.0

    result = re.search(r'MemTotal:\s*(?P<memkb>\d+) kB', process_output)
    if result:
        total_available_ram_gb = int(result.group('memkb')) / 1000000.0
    else:
        print(f'Unable to parse the output of /proc/meminfo to get available total RAM.')
        print(f'{process_output}')
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
This next step will install Geth, an Eth1 client.

It uses the official Ethereum Personal Package Archive (PPA) meaning that
it gets integrated with the normal updates for Ubuntu and its related
tools like APT.

Once the installation is completed, it will create a systemd service that
will automatically start Geth on reboot or if it crashes. Geth will be
started and you will slowly start syncing with the Ethereum 1.0 network.
This syncing process can take a few hours or days even with good hardware
and good internet. We will perform a few tests to make sure Geth is running
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

        print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False

    # Wait a little before checking for Geth syncing since it can be slow to start
    print('We are giving Geth a few seconds to start before testing syncing.')
    time.sleep(2)
    try:
        subprocess.run([
            'journalctl', '-fu', geth_service_name
        ], timeout=30)
    except subprocess.TimeoutExpired:
        pass

    # Verify proper Geth syncing
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

        print(
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

        print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
We received an unexpected response from geth HTTP-RPC server. This is
likely because geth has not started syncing yet or because it's taking a
little longer to find peers. We suggest you wait and retry in a minute.
Here are some details for this last test we tried to perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()

        if not result:

            print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

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
'''             ),
                buttons=[
                    ('Quit', False)
                ]
            ).run()

            print(
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

            print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
            )

            return False

        response_json = response.json()

    if (
        not response_json or
        'result' not in response_json or
        not response_json['result']
    ):
        # We could not get a proper result from Geth after all those retries
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
After a few retries, we still received an unexpected response from geth
HTTP-RPC server. Here are some details for this last test we tried to
perform:

URL: {local_geth_jsonrpc_url}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False

    response_result = response_json['result']

    if 'currentBlock' not in response_result:
        result = button_dialog(
            title='Unexpected response from Geth',
            text=(
f'''
The response from the eth_syncing JSON-RPC call on Geth HTTP-RPC server
was unexpected. Here are some details for this call:

result field: {json.dumps(response_result)}

We cannot proceed if the geth HTTP-RPC server is not responding properly.
Make sure to check the logs and fix any issue found there. You can see the
logs with:

$ sudo journalctl -ru {geth_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your geth service logs, type the following command:

$ sudo journalctl -ru {geth_service_name}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
Geth is currently syncing properly.

currentBlock: {int(response_result.get('currentBlock', '0x0'), base=16)}
highestBlock: {int(response_result.get('highestBlock', '0x0'), base=16)}
knownStates: {int(response_result.get('knownStates', '0x0'), base=16)}
pulledStates: {int(response_result.get('pulledStates', '0x0'), base=16)}
startingBlock: {int(response_result.get('startingBlock', '0x0'), base=16)}

Raw result: {response_result}
''')
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
This next step will install Lighthouse, an Eth2 client that includes a
beacon node and a validator client in the same binary.

It will download the official binary from GitHub, verify its PGP signature
and extract it for easy use.

Once installed locally, it will create a systemd service that will
automatically start the Lighthouse beacon node on reboot or if it crashes.
The beacon node will be started and you will slowly start syncing with the
Ethereum 2.0 network. This syncing process can take a few hours or days
even with good hardware and good internet.
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
            print('Cannot connect to Github')
            return False

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            print('Github returned error code')
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
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
            # TODO: Better handling of missing asset in latest release
            print('Could not find binary or signature asset in Github release')
            return False
        
        # Downloading latest Lighthouse release files
        download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])

        try:
            with open(binary_path, 'wb') as binary_file:
                with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print('Exception while downloading Lighthouse binary from Github')
            return False
        
        signature_path = Path(download_path, signature_asset['file_name'])

        try:
            with open(signature_path, 'wb') as signature_file:
                with httpx.stream('GET', signature_asset['file_url']) as http_stream:
                    for data in http_stream.iter_bytes():
                        signature_file.write(data)
        except httpx.RequestError as exception:
            print('Exception while downloading Lighthouse signature from Github')
            return False

        # Install gpg using APT
        subprocess.run([
            'apt', '-y', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'gpg'])

        # Verify PGP signature
        command_line = ['gpg', '--keyserver', 'pool.sks-keyservers.net', '--recv-keys',
            LIGHTHOUSE_PRIME_PGP_KEY_ID]
        process_result = subprocess.run(command_line)

        retry_count = 5
        if process_result.returncode != 0:
            # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
            retry_index = 0
            while process_result.returncode != 0 and retry_index < retry_count:
                retry_index = retry_index + 1
                print('GPG failed to download the PGP key. We will wait 10 seconds and try again.')
                time.sleep(10)
                process_result = subprocess.run(command_line)
        
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP key download
            print(
f'''
We failed to download the Sigma Prime\'s PGP key to verify the lighthouse
binary after {retry_count} retries.
'''
)
            return False
        
        process_result = subprocess.run([
            'gpg', '--verify', signature_path])
        if process_result.returncode != 0:
            # TODO: Better handling of failed PGP signature
            print('The lighthouse binary signature is wrong. We will stop here to protect you.')
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
    
    print(
'''
We are giving the lighthouse beacon node a few seconds to start before testing
it.

You might see some error and warn messages about your eth1 node not being in
sync, being far behind or about the beacon node being unable to connect to any
eth1 node. Those message are normal to see while your eth1 client is syncing.
'''
)
    time.sleep(6)
    try:
        subprocess.run([
            'journalctl', '-fu', lighthouse_bn_service_name
        ], timeout=30)
    except subprocess.TimeoutExpired:
        pass

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

        print(
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

        print(
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

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    # Verify proper Lighthouse beacon node syncing
    lighthouse_bn_syncing_query = BN_SYNCING_EP
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_syncing_query
    headers = {
        'accept': 'application/json'
    }
    try:
        response = httpx.get(lighthouse_bn_query_url, headers=headers)
    except httpx.RequestError as exception:
        button_dialog(
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

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    if response.status_code != 200:
        button_dialog(
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

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False
    
    response_json = response.json()

    retry_index = 0
    retry_count = 5

    while (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ) and retry_index < retry_count:
        result = button_dialog(
            title='Unexpected response from Lighthouse beacon node',
            text=(
f'''
We received an unexpected response from the lighthouse beacon node HTTP
server. This is likely because lighthouse has not started syncing yet or
because it's taking a little longer to find peers. We suggest you wait and
retry in a minute. Here are some details for this last test we tried to
perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Retry', 1),
                ('Quit', False)
            ]
        ).run()
        
        if not result:

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False
        
        retry_index = retry_index + 1

        # Wait a little before the next retry
        time.sleep(5)

        try:
            response = httpx.get(lighthouse_bn_query_url, headers=headers)
        except httpx.RequestError as exception:
            button_dialog(
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

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False

        if response.status_code != 200:
            button_dialog(
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

            print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
            )

            return False
        
        response_json = response.json()
    
    if (
        'data' not in response_json or
        'is_syncing' not in response_json['data'] or
        not response_json['data']['is_syncing']
    ):
        # We could not get a proper result from the Lighthouse beacon node after all those retries
        result = button_dialog(
            title='Unexpected response from Lighthouse beacon node',
            text=(
f'''
After a few retries, we still received an unexpected response from the
lighthouse beacon node HTTP server. Here are some details for this last
test we tried to perform:

URL: {lighthouse_bn_query_url}
Method: GET
Headers: {headers}
Response: {json.dumps(response_json)}

We cannot proceed if the lighthouse beacon node HTTP server is not
responding properly. Make sure to check the logs and fix any issue found
there. You can see the logs with:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''         ),
            buttons=[
                ('Quit', False)
            ]
        ).run()

        print(
f'''
To examine your lighthouse beacon node service logs, type the following
command:

$ sudo journalctl -ru {lighthouse_bn_service_name}
'''
        )

        return False

    # TODO: Using async and prompt_toolkit asyncio loop to display syncing values updating
    # in realtime for a few seconds

    print(
f'''
The lighthouse beacon node is currently syncing properly.

Head slot: {response_json['data'].get('head_slot', 'unknown')}
Sync distance: {response_json['data'].get('sync_distance', 'unknown')}

Raw data: {response_json['data']}
''' )
    time.sleep(5)

    return True

def obtain_keys(network):
    # Obtain validator keys for the selected network

    # Check if there are keys already imported
    eth2_deposit_cli_path = Path(Path.home(), 'eth2validatorwizard', 'eth2depositcli')
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
                generated_keys['deposit_data_path'] is None or
                len(generated_keys['keystore_paths']) == 0):
                print(f'No key has been found while importing them from {validator_keys_path}')
            else:
                actual_keys = imported_keys
                obtained_keys = True

            continue

        result = button_dialog(
            title='Generating keys',
            text=(HTML(
f'''
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
                # TODO: Better handling for network response issue
                print(
f'Cannot get latest eth2.0-deposit-cli release from Github. Exception {exception}'
                )
                return False

            if response.status_code != 200:
                # TODO: Better handling for network response issue
                print(
f'Cannot get latest eth2.0-deposit-cli release from Github. Error code {response.status_code}'
                )
                return False
            
            release_json = response.json()

            if 'assets' not in release_json:
                # TODO: Better handling on unexpected response structure
                print('Unexpected response from Github API.')
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
                # TODO: Better handling of missing binary in latest release
                print('No eth2.0-deposit-cli binary found in Github release')
                return False
            
            checksum_path = None

            if checksum_asset is None:
                # TODO: Better handling of missing checksum in latest release
                print('Warning: No eth2.0-deposit-cli checksum found in Github release')
            
            # Downloading latest eth2.0-deposit-cli release files
            download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
            download_path.mkdir(parents=True, exist_ok=True)

            binary_path = Path(download_path, binary_asset['file_name'])
            binary_hash = hashlib.sha256()

            try:
                with open(binary_path, 'wb') as binary_file:
                    with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                        for data in http_stream.iter_bytes():
                            binary_file.write(data)
                            binary_hash.update(data)
            except httpx.RequestError as exception:
                print('Exception while downloading eth2.0-deposit-cli binary from Github')
                return False

            if checksum_asset is not None:
                binary_hexdigest = binary_hash.hexdigest()

                checksum_path = Path(download_path, checksum_asset['file_name'])

                try:
                    with open(checksum_path, 'wb') as signature_file:
                        with httpx.stream('GET', checksum_asset['file_url']) as http_stream:
                            for data in http_stream.iter_bytes():
                                signature_file.write(data)
                except httpx.RequestError as exception:
                    print('Exception while downloading eth2.0-deposit-cli checksum from Github')
                    return False

                # Verify SHA256 signature
                with open(checksum_path, 'r') as signature_file:
                    if binary_hexdigest != signature_file.read(1024).strip():
                        # SHA256 checksum failed
                        # TODO: Better handling of failed SHA256 checksum
                        print('SHA256 checksum failed on eth2.0-deposit-cli binary from Github')
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
            # TODO: Better handling of no keys generated
            print('No key has been generated with the eth2.0-deposit-cli tool.')
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
        title='Lighthouse validator client',
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
        print('No keystore files found to import. We\'ll guess they were already imported for now.')
        time.sleep(2)

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
    
    print(
f'''
We found {len(public_keys)} key(s) imported into the lighthouse validator client.
'''
    )
    time.sleep(2)

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
    print(
'''
We are giving the lighthouse validator client a few seconds to start before
testing it.

You might see some error and warn messages about your beacon node not being
synced or about a failure to download validator duties. Those message are
normal to see while your beacon node is syncing.
'''
    )
    time.sleep(6)
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

        print(
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

On the Eth2 Launchpad website, you will be asked a few questions and it
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
        # TODO: Better handling of no public keys in deposit data file
        print('No public key(s) found in the deposit file.')
        return False

    # Verify that the deposit was done correctly using beaconcha.in API
    validator_deposits = get_bc_validator_deposits(network, public_keys)

    if type(validator_deposits) is not list and not validator_deposits:
        # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
        print('Unability to get validator(s) deposits from beaconcha.in')
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

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
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

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
            return False

    # Clean up deposit data file
    deposit_file_copy_path.unlink()
    os.unlink(keys['deposit_data_path'])
    
    return public_keys
