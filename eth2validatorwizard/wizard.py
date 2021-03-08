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
from urllib.parse import urlparse

from eth2validatorwizard import __version__
from eth2validatorwizard.constants import *

from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, input_dialog

def run():
    # Main entry point for the wizard.

    if not show_welcome():
        # User asked to quit
        quit()

    self_update()

    if not has_su_perm():
        # User is not a super user
        show_not_su()
        quit()

    # TODO: Detect if installation is already started and resume if needed

    if not explain_overview():
        # User asked to quit
        quit()

    # TODO: Check for open ports
    # TODO: Check for disk size
    # TODO: Check for disk speed
    # TODO: Check for internet speed
    # TODO: Check time synchronization and configure it if needed

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit()

    if not install_geth(selected_network):
        # User asked to quit or error
        quit()

    eth1_fallbacks = select_eth1_fallbacks(selected_network)
    if type(eth1_fallbacks) is not list and not eth1_fallbacks:
        # User asked to quit
        quit()

    if not install_lighthouse(selected_network, eth1_fallbacks):
        # User asked to quit or error
        quit()

    generated_keys = generate_keys(selected_network)
    if not generated_keys:
        # User asked to quit or error
        quit()
    
    if not install_lighthouse_validator(selected_network, generated_keys):
        # User asked to quit or error
        quit()

    public_keys = initiate_deposit(selected_network, generated_keys)
    if not public_keys:
        # User asked to quit or error
        quit()

    # TODO: Monitoring setup

    show_whats_next(selected_network, generated_keys, public_keys)

    show_public_keys(selected_network, generated_keys, public_keys)

def show_welcome():
    # Show a welcome message about this wizard

    result = button_dialog(
        title='Eth2 Validator Wizard',
        text=(
'''
Welcome to the Eth2 Validator Wizard!

This setup assistant is meant to guide anyone through the different steps
to become a fully functional validator on the Ethereum 2.0 network. It will
install and configure all the software needed to become a validator.

If you have any question or if you need additional support, make sure
to get in touch with the ethstaker community on:

* Discord: discord.gg/e84CFep
* Reddit: reddit.com/r/ethstaker
'''     ),
        buttons=[
            ('Start', True),
            ('Quit', False)
        ]
    ).run()

    return result

def self_update():
    # TODO: Check for a new version of the wizard and self-update if needed

    pass

def has_su_perm():
    # Check to see if the script has super user (root or sudo) permissions

    return os.geteuid() == 0

def show_not_su():
    # Show a message about the wizard not having super user (root or sudo) permissions

    button_dialog(
        title='Not a super user',
        text=(
'''
The Eth2 Validator Wizard needs to have super user permissions in order
to proceed.

A simple way to give the wizard these permissions is to start it with sudo.
'''     ),
        buttons=[
            ('Quit', False)
        ]
    ).run()

def explain_overview():
    # Explain the overall process of becoming a validator

    result = button_dialog(
        title='Becoming a validator',
        text=(
'''
Here is an overview of the different steps required to become an active
validator on an Ethereum 2.0 network.

* Consolidate 32 ETH for each active validator you want (You can have
an almost unlimited amount of active validators using a single computer
and this setup)
* Install an Eth1 client and let it synchronize
* Install an Eth2 beacon node and let it synchronize
* Generate your validator(s) keys
* Install an Eth2 validator client and import your key(s)
* Perform the 32 ETH deposit for each validator
* Wait for your validator(s) to become active (can take a few hours/days)
'''     ),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def select_network():
    # Prompt for the selection on which network to perform the installation

    result = radiolist_dialog(
        title='Network selection',
        text=(
'''
This wizard supports installing and configuring software for various
Ethereum 2.0 networks. Mainnet is the main network with real value. The
others are mostly for testing and they do not use anything of real value.

For which network would you like to perform this installation?

* Press the tab key to switch between the controls below
'''
        ),
        values=[
            (NETWORK_MAINNET, "Mainnet"),
            (NETWORK_PYRMONT, "Pyrmont")
        ],
        ok_text='Use this',
        cancel_text='Quit'
    ).run()

    return result

def install_geth(network):
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
            'apt', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'geth'])
    
    # Check if Geth user or directory already exists
    geth_datadir = Path('/var/lib/goethereum')
    if geth_datadir.exists and geth_datadir.is_dir():
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
    with open('/etc/systemd/system/' + geth_service_name, 'w') as service_file:
        service_file.write(GETH_SERVICE_DEFINITION[network])
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
    response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)

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
We received an unexpected response from geth HTTP-RPC server. Here are
some details for this last test we tried to perform:

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

        response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)

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

def select_eth1_fallbacks(network):
    # Prompt the user for eth1 fallback nodes
    eth1_fallbacks = []

    add_more_fallbacks = True
    eth1_network_name = ETH1_NETWORK_NAME[network]
    eth1_network_chainid = ETH1_NETWORK_CHAINID[network]

    while add_more_fallbacks:
        skip_done_button_label = 'Skip'
        if len(eth1_fallbacks) > 0:
            skip_done_button_label = 'Done'

        result = button_dialog(
            title='Adding Eth1 fallback nodes',
            text=(
f'''
Having eth1 fallback nodes is highly recommended for your beacon node. It
will provide eth1 data even when your Geth client is syncing, out of sync
or when it is down.

You can find a good list of public eth1 nodes available on:

https://ethereumnodes.com/

We recommend creating a free account with at least Infura and Alchemy and
adding their endpoints as your eth1 fallback nodes. Make sure to choose the
correct eth1 network in your project: {eth1_network_name} .

{len(eth1_fallbacks)} eth1 fallback node(s) added so far.

Do you want add one or more eth1 fallback node?
'''         ),
            buttons=[
                ('Add more', 1),
                (skip_done_button_label, 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 2:
            add_more_fallbacks = False
            break
    
        uri_valid = False
        eth1_fallback = None
        input_canceled = False

        while not uri_valid:
            not_valid_msg = ''
            if eth1_fallback is not None:
                not_valid_msg = (
'''

Your last input was an invalid URL. Please make sure to enter a valid URL.'''
                )

            eth1_fallback = input_dialog(
                title='New Eth1 fallback node',
                text=(
f'''
Please enter your Eth1 fallback endpoint:

It usually starts with 'https://' and it usally includes a unique id which
you should keep secret if you used a service that requires an account.

* Press the tab key to switch between the controls below{not_valid_msg}
'''         )).run()

            if not eth1_fallback:
                input_canceled = True
                break
            
            uri_valid = uri_validator(eth1_fallback)

        if input_canceled:
            # User clicked the cancel button
            continue

        # Verify if the endpoint is working properly and is on the correct chainId
        request_json = {
            'jsonrpc': '2.0',
            'method': 'eth_chainId',
            'id': 1
        }
        headers = {
            'Content-Type': 'application/json'
        }

        try:
            response = httpx.post(eth1_fallback, json=request_json, headers=headers)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to Eth1 fallback endpoint',
                text=(
f'''
We could not connect to this Eth1 fallback endpoint. Here are some details
for this last test we tried to perform:

URL: {eth1_fallback}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Exception: {exception}

Make sure you enter your endpoint correctly.
'''         ),
                buttons=[
                    ('Retry', False)
                ]
            ).run()

            continue

        if response.status_code != 200:
            result = button_dialog(
                title='Cannot connect to Eth1 fallback endpoint',
                text=(
f'''
We could not connect to this eth1 fallback endpoint. Here are some details
for this last test we tried to perform:

URL: {eth1_fallback}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Status code: {response.status_code}

Make sure you enter your endpoint correctly.
'''         ),
                buttons=[
                    ('Retry', False)
                ]
            ).run()

            continue

        response_json = response.json()

        if (
            not response_json or
            'result' not in response_json or
            not response_json['result'] or
            type(response_json['result']) is not str
        ):
            # We could not get a proper result from the eth1 endpoint
            result = button_dialog(
                title='Unexpected response from Eth1 fallback endpoint',
                text=(
f'''
We received an unexpected response from this eth1 fallback endpoint. Here
are some details for this last test we tried to perform:

URL: {eth1_fallback}
Method: POST
Headers: {headers}
JSON payload: {json.dumps(request_json)}
Response: {json.dumps(response_json)}

Make sure you enter your endpoint correctly and that it's a working eth1
endpoint.
'''         ),
                buttons=[
                    ('Retry', False)
                ]
            ).run()

            continue
        
        eth1_fallback_chainid = int(response_json['result'], base=16)

        if eth1_fallback_chainid != eth1_network_chainid:
            result = button_dialog(
                title='Unexpected chain id from Eth1 fallback endpoint',
                text=(
f'''
We received an unexpected chain id response from this eth1 fallback
endpoint. Here are some details for this:

Expected chain id: {eth1_network_chainid}
Received chain id: {eth1_fallback_chainid}

Did you select an eth1 endpoint with the proper network? It should be the
eth1 network: {eth1_network_name}

Make sure you enter your endpoint network is matching the network you
selected at the beginning of this wizard.
'''         ),
                buttons=[
                    ('Retry', False)
                ]
            ).run()

            continue

        eth1_fallbacks.append(eth1_fallback)

    return eth1_fallbacks

def uri_validator(uri):
    try:
        result = urlparse(uri)
        return all([result.scheme, result.netloc, result.path])
    except:
        return False

def install_lighthouse(network, eth1_fallbacks):
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
        response = httpx.get(lighthouse_gh_release_url, headers=headers)

        if response.status_code != 200:
            # TODO: Better handling for network response issue
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
            return False
        
        # Downloading latest Lighthouse release files
        download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])

        with open(binary_path, 'wb') as binary_file:
            with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
        
        signature_path = Path(download_path, signature_asset['file_name'])

        with open(signature_path, 'wb') as signature_file:
            with httpx.stream('GET', signature_asset['file_url']) as http_stream:
                for data in http_stream.iter_bytes():
                    signature_file.write(data)

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
            print('The lighthouse binary signature is wrong. We\'ll stop here to protect you.')
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
    service_definition = service_definition.format(eth1endpoints=','.join(eth1_endpoints))

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
    
    lighthouse_bn_version_query = '/eth/v1/node/version'
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_version_query
    headers = {
        'accept': 'application/json'
    }
    response = httpx.get(lighthouse_bn_query_url, headers=headers)

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
    lighthouse_bn_syncing_query = '/eth/v1/node/syncing'
    lighthouse_bn_query_url = local_lighthouse_bn_http_base + lighthouse_bn_syncing_query
    headers = {
        'accept': 'application/json'
    }
    response = httpx.get(lighthouse_bn_query_url, headers=headers)

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
server. Here are some details for this last test we tried to perform:

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

        response = httpx.get(lighthouse_bn_query_url, headers=headers)

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

def generate_keys(network):
    # Generate validator keys for the selected network

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

            # We want to generate new keys from here
    
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
        title='Generating keys',
        text=(
f'''
This next step will generate the keys needed to be a validator.

It will download the official eth2.0-deposit-cli binary from GitHub,
verify its SHA256 checksum, extract it and start it.

The eth2.0-deposit-cli tool is executed in an interactive way where you
have to answer a few questions. It will help you create a mnemonic from
which all your keys will be derived from. The mnemonic is the ultimate key.
It is VERY IMPORTANT to securely and privately store your mnemonic. It can
be used to recreate your validator keys and eventually withdraw your funds.

When asked how many validators you wish to run, remember that you will have
to do a 32 {currency} deposit for each validator.
'''     ),
        buttons=[
            ('Generate', True),
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
'''         ),
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
        response = httpx.get(eth2_cli_gh_release_url, headers=headers)

        if response.status_code != 200:
            # TODO: Better handling for network response issue
            return False
        
        release_json = response.json()

        if 'assets' not in release_json:
            # TODO: Better handling on unexpected response structure
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

        if binary_asset is None or checksum_asset is None:
            # TODO: Better handling of missing asset in latest release
            return False
        
        # Downloading latest eth2.0-deposit-cli release files
        download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        binary_path = Path(download_path, binary_asset['file_name'])
        binary_hash = hashlib.sha256()

        with open(binary_path, 'wb') as binary_file:
            with httpx.stream('GET', binary_asset['file_url']) as http_stream:
                for data in http_stream.iter_bytes():
                    binary_file.write(data)
                    binary_hash.update(data)

        binary_hexdigest = binary_hash.hexdigest()

        checksum_path = Path(download_path, checksum_asset['file_name'])

        with open(checksum_path, 'wb') as signature_file:
            with httpx.stream('GET', checksum_asset['file_url']) as http_stream:
                for data in http_stream.iter_bytes():
                    signature_file.write(data)

        # Verify SHA256 signature
        with open(checksum_path, 'r') as signature_file:
            if binary_hexdigest != signature_file.read(1024).strip():
                # SHA256 checksum failed
                # TODO: Better handling of failed SHA256 checksum
                return False
        
        # Extracting the eth2.0-deposit-cli binary archive
        eth2_deposit_cli_path.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            'tar', 'xvf', binary_path, '--strip-components', '2', '--directory',
            eth2_deposit_cli_path])
        
        # Remove download leftovers
        binary_path.unlink()
        checksum_path.unlink()

    # Clean potential leftover keys
    if validator_keys_path.exists():
        if validator_keys_path.is_dir():
            shutil.rmtree(validator_keys_path)
        elif validator_keys_path.is_file():
            validator_keys_path.unlink()
    
    # Launch eth2.0-deposit-cli
    subprocess.run([
        eth2_deposit_cli_binary, 'new-mnemonic', '--chain', network],
        cwd=eth2_deposit_cli_path)

    # Clean up eth2.0-deposit-cli binary
    eth2_deposit_cli_binary.unlink()

    # Verify the generated keys
    generated_keys = search_for_generated_keys(validator_keys_path)
    
    if generated_keys['deposit_data_path'] is None or len(generated_keys['keystore_paths']) == 0:
        # TODO: Better handling of no keys generated
        print('No key has been generated with the eth2.0-deposit-cli tool. We cannot continue.')
        return False

    return generated_keys

def search_for_generated_keys(validator_keys_path):
    # Search for keys generated with the eth2.0-deposit-cli binary

    deposit_data_path = None
    keystore_paths = []

    if validator_keys_path.exists() and validator_keys_path.is_dir():
        with os.scandir(validator_keys_path) as dir_it:
            for entry in dir_it:
                if entry.name.startswith('.') or not entry.is_file():
                    continue

                if entry.name.startswith('deposit_data'):
                    deposit_data_path = entry.path
                elif entry.name.startswith('keystore'):
                    keystore_paths.append(entry.path)
    
    return {
        'validator_keys_path': validator_keys_path,
        'deposit_data_path': deposit_data_path,
        'keystore_paths': keystore_paths
    }

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
        text=(
'''
This next step will import your keystore(s) to be used with the Lighthouse
validator client and it will configure the Lighthouse validator client.

During the importation process, you will be asked to enter the password
you typed during the keys generation step. It is not your mnemonic. Do not
omit typing your password during this importation process.

It will create a systemd service that will automatically start the
Lighthouse validator client on reboot or if it crashes. The validator
client will be started, it will connect to your beacon node and it will be
ready to start validating once your validator(s) get activated.
'''     ),
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
        title='Deposit on the launch pad',
        text=(
f'''
This next step is to perform the 32 {currency} deposit(s) on the launch pad. In
order to do this deposit, you will need your deposit file which was created
during the key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

On the Eth2 Launch Pad website, you will be asked a few questions and it
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

def get_bc_validator_deposits(network, public_keys):
    # Return the validator deposits from the beaconcha.in API

    pubkey_arg = ','.join(public_keys)
    bc_api_query_url = (BEACONCHA_IN_URLS[network] +
        BEACONCHA_VALIDATOR_DEPOSITS_API_URL.format(indexOrPubkey=pubkey_arg))
    headers = {'accept': 'application/json'}
    response = httpx.get(bc_api_query_url, headers=headers)

    if response.status_code != 200:
        # TODO: Better handling for network response issue
        print(f'Error code {response.status_code} when trying to get {bc_api_query_url}')
        return False
    
    response_json = response.json()

    if (
        'status' not in response_json or
        response_json['status'] != 'OK' or
        'data' not in response_json
        ):
        # TODO: Better handling for response data or structure issue
        print(f'Unexpected response data or structure from {bc_api_query_url}: {response_json}')
        return False
    
    validator_deposits = response_json['data']
    # beaconcha.in API does not return a list for a single validator so
    # we make it a list for ease of use
    if type(validator_deposits) is not list:
        validator_deposits = [validator_deposits]

    return validator_deposits

def show_whats_next(network, keys, public_keys):
    # Show what's next including wait time

    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    button_dialog(
        title='Installation completed',
        text=(
f'''
You just completed all the steps needed to become an active validator on
the {network.capitalize()} Ethereum 2.0 network. You created {len(keys['keystore_paths'])} validator(s)
that will soon be activated.

You can monitor your activation period and all the details about your
validator(s) on the beaconcha.in website at the following URL:

{beaconcha_in_url}

If you have any question or if you need additional support, make sure
to get in touch with the ethstaker community on:

* Discord: discord.gg/e84CFep
* Reddit: reddit.com/r/ethstaker
'''     ),
        buttons=[
            ('Quit', False)
        ]
    ).run()

def show_public_keys(network, keys, public_keys):
    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    newline = '\n'

    print(
f'''
Eth2 Validator Wizard completed!

Network: {network.capitalize()}
Number of validator(s): {len(keys['keystore_paths'])}

Make sure to note or save your public keys somewhere. Your validator public
key(s) are:
{newline.join(public_keys)}

Make sure to check the beaconcha.in website for more details about your
validator(s):
{beaconcha_in_url}
''' )