import httpx
import json
import os
import time
import humanize

from rfc3986 import urlparse, builder as urlbuilder

from datetime import timedelta

from pathlib import Path

from eth2validatorwizard.constants import *

from asyncio import get_event_loop

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import radiolist_dialog, button_dialog, input_dialog
from prompt_toolkit.shortcuts.dialogs import _return_none, _create_app

from typing import Optional, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.filters import FilterOrBool
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import BaseStyle
from prompt_toolkit.validation import Validator
from prompt_toolkit.eventloop import run_in_executor_with_context

from prompt_toolkit.widgets import (
    Box,
    Button,
    Dialog,
    Label,
    ProgressBar,
    TextArea,
    ValidationToolbar,
)

def select_network():
    # Prompt for the selection on which network to perform the installation

    unknown_joining_queue = '(No join queue information found)'

    network_queue_info = {
        NETWORK_MAINNET: unknown_joining_queue,
        NETWORK_PYRMONT: unknown_joining_queue,
        NETWORK_PRATER: unknown_joining_queue
    }

    headers = {
        'accept': 'application/json'
    }

    for network in network_queue_info.keys():
        beaconcha_in_queue_query_url = (
            BEACONCHA_IN_URLS[network] + BEACONCHA_VALIDATOR_QUEUE_API_URL)
        try:
            response = httpx.get(beaconcha_in_queue_query_url, headers=headers)
        except httpx.RequestError as exception:
            print(f'Exception: {exception} while querying beaconcha.in.')
            continue

        if response.status_code != 200:
            print(f'Status code: {response.status_code} while querying beaconcha.in.')
            continue

        response_json = response.json()

        if (
            response_json and
            'data' in response_json and
            'beaconchain_entering' in response_json['data']):
            validators_entering = int(response_json['data']['beaconchain_entering'])
            waiting_td = timedelta(days=validators_entering / 900.0)

            network_queue_info[network] = (
                f'({validators_entering} validators waiting to join '
                f'[{humanize.naturaldelta(waiting_td)}])'
            )

    result = radiolist_dialog(
        title='Network selection',
        text=(
'''
This wizard supports installing and configuring software for various
Ethereum 2.0 networks. Mainnet is the main network with real value. The
others are mostly for testing and they do not use anything of real value.

Joining a beacon chain network as a validator can take extra time if many
validators are trying to join at the same time. The amount of validators in
the join queue and the estimated time is displayed below for each network.

For which network would you like to perform this installation?

* Press the tab key to switch between the controls below
'''
        ),
        values=[
            (NETWORK_MAINNET, f'Mainnet {network_queue_info[NETWORK_MAINNET]}'),
            (NETWORK_PYRMONT, f'Pyrmont {network_queue_info[NETWORK_PYRMONT]}'),
            (NETWORK_PRATER, f'Prater {network_queue_info[NETWORK_PRATER]}')
        ],
        ok_text='Use this',
        cancel_text='Quit'
    ).run()

    return result

def select_custom_ports(ports):
    # Prompt the user for modifying the default ports

    result = button_dialog(
        title='Open ports configuration',
        text=(HTML(
f'''
In order to improve your ability to connect with peers, you should have
exposed ports to the Internet on your machine. Here are the default open
ports needed for this:

Ethereum 1 node: {ports['eth1']} (TCP/UDP)
Ethereum 2 beacon node: {ports['eth2_bn']} (TCP/UDP)

If this machine is behind a router or another network device that blocks
incoming connections on those ports, you will have to configure those
devices so that they can forward (port forward) those connections to this
machine. If you need help with this, read your device's manual, search for
"How to Forward Ports" for your device or ask the ETHStaker community.

Do you want to use the default ports?
'''     )),
        buttons=[
            ('Default', 1),
            ('Custom', 2),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    if result == 1:
        return ports
    
    if result == 2:
        valid_port = False
        entered_port = None
        input_canceled = False

        while not valid_port:
            not_valid_msg = ''
            if entered_port is not None:
                not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>not a valid port</b>. Please make sure to enter a valid
port.</style>'''
                )

            entered_port = input_dialog(
                title='Custom port for Ethereum 1 node',
                text=(HTML(
f'''
Please enter your custom port for your Ethereum 1 node:

The default port is {ports['eth1']} (TCP/UDP)

That port number should be greater than 1024 and lower than 65535.

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

            if not entered_port:
                input_canceled = True
                break
        
            entered_port = entered_port.strip()

            try: 
                entered_port = int(entered_port)
            except ValueError:
                continue

            if not (1024 <= entered_port <= 65535):
                continue
            
            valid_port = True

        if valid_port:
            ports['eth1'] = entered_port
        
        valid_port = False
        entered_port = None
        input_canceled = False

        while not valid_port:
            not_valid_msg = ''
            if entered_port is not None:
                not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>not a valid port</b>. Please make sure to enter a valid
port.</style>'''
                )

            entered_port = input_dialog(
                title='Custom port for Ethereum 2 beacon node',
                text=(HTML(
f'''
Please enter your custom port for your Ethereum 2 beacon node:

The default port is {ports['eth2_bn']} (TCP/UDP)

That port number should be greater than 1024 and lower than 65535. It
should also be different from the one you choose for Ethereum 1 node.

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

            if not entered_port:
                input_canceled = True
                break
        
            entered_port = entered_port.strip()

            try: 
                entered_port = int(entered_port)
            except ValueError:
                continue

            if not (1024 <= entered_port <= 65535):
                continue
            
            if entered_port == ports['eth1']:
                continue
            
            valid_port = True

        if valid_port:
            ports['eth2_bn'] = entered_port
    
    return ports

def select_initial_state(network):
    # Prompt the user for initial state provider (weak subjectivity checkpoint)

    infura_bn_domain = INFURA_BEACON_NODE_DOMAINS[network]

    initial_state_url = None

    while initial_state_url is None:

        result = button_dialog(
                title='Adding initial state provider',
                text=(HTML(
f'''
Having an initial state provider is highly recommended for your beacon
node. It makes it possible to get a fully synced beacon in just a few
minutes compared to having to wait hours or days.

An easy way to get a provider is to create a free account on Infura. Your
Infura account can also be used later on in the wizard to provide an eth1
fallback node.

https://infura.io/

If you have access to a custom beacon node, you can enter your own URL to
that beacon node with the custom option. That beacon node should be on the
<b>{network.capitalize()}</b> Ethereum 2.0 network.

Do you want add an initial state provider?
'''             )),
                buttons=[
                    ('Infura', 1),
                    ('Custom', 2),
                    ('Skip', 3),
                    ('Quit', False)
                ]
            ).run()
        
        if not result:
            return result
        
        if result == 3:
            return ''
        elif result == 1:
            valid_url = False
            infura_credentials = None
            input_canceled = False

            while not valid_url:
                not_valid_msg = ''
                initial_state_url = None
                if infura_credentials is not None:
                    not_valid_msg = (
'''

<style bg="red" fg="black">Your last input were <b>not valid credentials</b>. Please make sure to enter
valid credentials from Infura.</style>'''
                    )

                infura_credentials = input_dialog(
                    title='Initial state provider using Infura',
                    text=(HTML(
f'''
Please enter your Infura ETH 2 project's credentials from:

https://infura.io/

Once you are logged into your Infura account, click on <b>DASHBOARD</b> button in
the top right corner. Click on the <b>ETH 2</b> button in the left column menu.
Click on <b>CREATE NEW PROJECT</b> button. Give it a name. You should see your
project settings, a <b>PROJECT ID</b> and a <b>PROJECT SECRET</b> in the <b>KEYS</b> section.
Enter those values separated by a colon in this format:

&lt;PROJECT ID&gt;:&lt;PROJECT SECRET&gt;

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

                if not infura_credentials:
                    input_canceled = True
                    break
            
                if ':' not in infura_credentials:
                    continue

                credentials = infura_credentials.split(':')
                username = credentials[0]
                password = credentials[1]

                initial_state_url = urlbuilder.URIBuilder(
                    ).add_scheme('https'
                    ).add_host(infura_bn_domain
                    ).add_credentials(username, password
                    ).finalize(
                    ).unsplit()
                
                valid_url = beacon_node_url_validator(network, initial_state_url)

            if input_canceled:
                # User clicked the cancel button
                continue

        elif result == 2:
            valid_url = False
            entered_url = None
            input_canceled = False

            while not valid_url:
                not_valid_msg = ''
                initial_state_url = None
                if entered_url is not None:
                    not_valid_msg = (
'''

<style bg="red" fg="black">Your last URL was <b>not valid beacon node</b>. Please make sure to enter a URL for
a valid beacon node.</style>'''
                    )

                entered_url = input_dialog(
                    title='Initial state provider using custom URL',
                    text=(HTML(
f'''
Please enter your beacon node URL:

It usually starts with 'https://' and it should point to the root of a
running beacon node on the <b>{network.capitalize()}</b> Ethereum 2.0 network that supports the
Eth2 Beacon Node API. It should implement these endpoints:

- {BN_DEPOSIT_CONTRACT_URL}
- {BN_FINALIZED_STATE_URL}

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

                if not entered_url:
                    input_canceled = True
                    break
            
                initial_state_url = entered_url
                
                valid_url = beacon_node_url_validator(network, initial_state_url)

            if input_canceled:
                # User clicked the cancel button
                continue
    
    if initial_state_url is not None:
        base_url = urlbuilder.URIBuilder.from_uri(initial_state_url)
        initial_state_url = base_url.add_path(BN_FINALIZED_STATE_URL).finalize().unsplit()

    return initial_state_url

def beacon_node_url_validator(network, url):
    # Return true if this is a beacon chain endpoint for the network

    if not uri_validator(url):
        return False
    
    base_url = urlbuilder.URIBuilder.from_uri(url)
    deposit_contract_url = base_url.add_path(BN_DEPOSIT_CONTRACT_URL).finalize().unsplit()

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = httpx.get(deposit_contract_url, headers=headers)

        if response.status_code != 200:
            print(f'Beacon node returned an unexpected status code: {response.status_code}')
            return False
        
        response_json = response.json()

        if not response_json:
            print(f'Unexpected response from beacon node.')
            return False

        if (
            'data' not in response_json or
            'chain_id' not in response_json['data'] or
            'address' not in response_json['data']
        ):
            print('Unexpected response from beacon node.')
            return False
        
        chain_id = response_json['data']['chain_id']
        deposit_contract = response_json['data']['address']

        if int(chain_id) != BN_CHAIN_IDS[network]:
            print(f'Unexpected chain_id ({chain_id}) from beacon node. We expected another value '
                f'({BN_CHAIN_IDS[network]}) for this network ({network}).')
            return False
        
        if deposit_contract.lower() != BN_DEPOSIT_CONTRACTS[network].lower():
            print(f'Unexpected deposit contract address ({deposit_contract}) from beacon node. '
                f'We expected another value ({BN_DEPOSIT_CONTRACTS[network]}) for this network ({network}).')
            return False
        
    except httpx.RequestError as exception:
        print(f'Exception during request to beacon node: {exception}')
        return False

    return True

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

<style bg="red" fg="black">Your last input was <b>an invalid URL</b>. Please make sure to enter a valid URL.</style>'''
                )

            eth1_fallback = input_dialog(
                title='New Eth1 fallback node',
                text=(HTML(
f'''
Please enter your Eth1 fallback endpoint:

It usually starts with 'https://' and it usally includes a unique id which
you should keep secret if you used a service that requires an account.

* Press the tab key to switch between the controls below{not_valid_msg}
'''         ))).run()

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
        return all([result.scheme, result.netloc])
    except:
        return False

def input_dialog_default(
    title: AnyFormattedText = "",
    text: AnyFormattedText = "",
    default_input_text = "",
    ok_text: str = "OK",
    cancel_text: str = "Cancel",
    completer: Optional[Completer] = None,
    validator: Optional[Validator] = None,
    password: FilterOrBool = False,
    style: Optional[BaseStyle] = None,
) -> Application[str]:
    """
    Display a text input box.
    Return the given text, or None when cancelled.
    """

    def accept(buf: Buffer) -> bool:
        get_app().layout.focus(ok_button)
        return True  # Keep text.

    def ok_handler() -> None:
        get_app().exit(result=textfield.text)

    ok_button = Button(text=ok_text, handler=ok_handler)
    cancel_button = Button(text=cancel_text, handler=_return_none)

    textfield = TextArea(
        text=default_input_text,
        multiline=False,
        password=password,
        completer=completer,
        validator=validator,
        accept_handler=accept,
    )

    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=text, dont_extend_height=True),
                textfield,
                ValidationToolbar(),
            ],
            padding=D(preferred=1, max=1),
        ),
        buttons=[ok_button, cancel_button],
        with_background=True,
    )

    return _create_app(dialog, style)

def progress_log_dialog(
    title: AnyFormattedText = "",
    text: AnyFormattedText = "",
    wait_text: str = "Wait",
    quit_text: str = "Quit",
    status_text: AnyFormattedText = "",
    run_callback: Callable[[Callable[[int], None], Callable[[str], None],
        Callable[[str], None], Callable[[dict], None], Callable[[], bool]], None] = (
        lambda *a: None
    ),
    style: Optional[BaseStyle] = None,
) -> Application[None]:
    """
    :param run_callback: A function that receives as input a `set_percentage`
        function and it does the work.
    """
    loop = get_event_loop()

    def wait_handler() -> None:
        pass

    def quit_handler() -> None:
        app = get_app()
        if not app.exited:
            app.exited = True
            app.exit(result=app.result)

    wait_button = Button(text=wait_text, handler=wait_handler)
    quit_button = Button(text=quit_text, handler=quit_handler)

    progressbar = ProgressBar()
    text_area = TextArea(
        focusable=False,
        # Prefer this text area as big as possible, to avoid having a window
        # that keeps resizing when we add text to it.
        height=D(preferred=10 ** 10),
        width=D(preferred=10 ** 10)
    )
    status = Label(text=status_text)

    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Box(Label(text=text)),
                Box(text_area, padding=D.exact(1)),
                Box(status, padding=D.exact(1)),
                progressbar,
            ]
        ),
        buttons=[wait_button, quit_button],
        with_background=True,
    )
    app = _create_app(dialog, style)
    app.result = None
    app.exited = False

    def set_percentage(value: int) -> None:
        progressbar.percentage = int(value)
        app.invalidate()

    def log_text(text: str) -> None:
        loop.call_soon_threadsafe(text_area.buffer.insert_text, text)
        app.invalidate()
    
    def change_status(text: str) -> None:
        status.formatted_text_control.text = text
        app.invalidate()
    
    def set_result(new_result: dict) -> None:
        app.result = new_result
    
    def get_exited() -> bool:
        return app.exited

    # Run the callback in the executor. When done, set a return value for the
    # UI, so that it quits.
    def start() -> None:
        result = None
        try:
            result = run_callback(set_percentage, log_text, change_status, set_result, get_exited)
        finally:
            if not app.exited:
                app.exited = True
                app.exit(result=result)

    def pre_run() -> None:
        run_in_executor_with_context(start)

    app.pre_run_callables.append(pre_run)

    return app

def search_for_generated_keys(validator_keys_path):
    # Search for keys generated with the eth2.0-deposit-cli binary

    deposit_data_path = None
    keystore_paths = []
    password_paths = []

    if validator_keys_path.is_dir():
        with os.scandir(validator_keys_path) as dir_it:
            for entry in dir_it:
                name = entry.name
                if name.startswith('.') or not entry.is_file():
                    continue

                if name.startswith('deposit_data'):
                    deposit_data_path = entry.path
                elif name.startswith('keystore') and name.endswith('.json'):
                    keystore_paths.append(entry.path)
                elif name.startswith('keystore') and name.endswith('.txt'):
                    password_paths.append(entry.path)
    
    return {
        'validator_keys_path': validator_keys_path,
        'deposit_data_path': deposit_data_path,
        'keystore_paths': keystore_paths,
        'password_paths': password_paths
    }

def get_bc_validator_deposits(network, public_keys):
    # Return the validator deposits from the beaconcha.in API

    pubkey_arg = ','.join(public_keys)
    bc_api_query_url = (BEACONCHA_IN_URLS[network] +
        BEACONCHA_VALIDATOR_DEPOSITS_API_URL.format(indexOrPubkey=pubkey_arg))
    headers = {'accept': 'application/json'}

    keep_retrying = True

    retry_index = 0
    retry_count = 5
    retry_delay = 30

    while keep_retrying and retry_index < retry_count:
        try:
            response = httpx.get(bc_api_query_url, headers=headers)
        except httpx.RequestError as exception:
            print(f'Exception {exception} when trying to get {bc_api_query_url}')

            retry_index = retry_index + 1
            print(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue

        if response.status_code != 200:
            print(f'Error code {response.status_code} when trying to get {bc_api_query_url}')
            
            retry_index = retry_index + 1
            print(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue
        
        response_json = response.json()

        if (
            'status' not in response_json or
            response_json['status'] != 'OK' or
            'data' not in response_json
            ):
            print(f'Unexpected response data or structure from {bc_api_query_url}: {response_json}')
            
            retry_index = retry_index + 1
            print(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue
        
        keep_retrying = False
    
    if keep_retrying:
        print(f'We failed to get the validator deposits from the beaconcha.in API after '
            f'{retry_count} retries.')
        time.sleep(5)
        return False
    
    validator_deposits = response_json['data']
    # beaconcha.in API does not return a list for a single validator so
    # we make it a list for ease of use
    if type(validator_deposits) is not list:
        validator_deposits = [validator_deposits]

    return validator_deposits

def test_open_ports(ports):
    # Test the selected ports to make sure they are opened and exposed to the internet

    params = {
        'ports': str(ports['eth1']) + ',' + str(ports['eth2_bn'])
    }

    requested_ports = {ports['eth1'], ports['eth2_bn']}

    all_ports_opened = False

    print('Checking for open ports...')

    while not all_ports_opened:
        try:
            print('Connecting to StakeHouse Port Checker...')
            response = httpx.get(STAKEHOUSE_PORT_CHECKER_URL, params=params)

            if response.status_code != 200:
                result = button_dialog(
                    title='Cannot connect to StakeHouse Port Checker',
                    text=(
f'''
We could not connect to StakeHouse Port Checker server. Here are some
details for this last test we tried to perform:

URL: {STAKEHOUSE_PORT_CHECKER_URL}
Method: GET
Parameters: {json.dumps(params)}
Status code: {response.status_code}

Would you like to retry?
'''                 ),
                    buttons=[
                        ('Retry', 1),
                        ('Skip', 2),
                        ('Quit', False)
                    ]
                ).run()
                
                if not result:
                    return result
                
                if result == 1:
                    time.sleep(5)
                    continue
            
                if result == 2:
                    break
            
            response_json = response.json()

            if (
                not response_json or
                'open_ports' not in response_json or
                type(response_json['open_ports']) is not list
            ):
                result = button_dialog(
                    title='Unexpected response from StakeHouse Port Checker',
                    text=(
f'''
We received an unexpected response from StakeHouse Port Checker server.
Here are some details for this last test we tried to perform:

URL: {STAKEHOUSE_PORT_CHECKER_URL}
Method: GET
Parameters: {json.dumps(params)}
Response: {json.dumps(response_json)}

Would you like to retry?
'''                 ),
                    buttons=[
                        ('Retry', 1),
                        ('Skip', 2),
                        ('Quit', False)
                    ]
                ).run()

                if not result:
                    return result
                
                if result == 1:
                    time.sleep(5)
                    continue
            
                if result == 2:
                    break
            
            opened_ports = set(response_json['open_ports'])

            if requested_ports != opened_ports:
                if len(opened_ports) == 0:
                    opened_ports = 'None'
                result = button_dialog(
                    title='Missing open ports',
                    text=(
f'''
It seems like you are missing some open ports. Here are some details for
this last test we tried to perform:

Tested ports: {requested_ports}
Open ports: {opened_ports}

In order to improve your ability to connect with peers, you should have
exposed ports to the Internet on your machine. If this machine is behind a
router or another network device that blocks incoming connections on those
ports, you will have to configure those devices so that they can forward
(port forward) those connections to this machine. If you need help with
this, read your device's manual, search for "How to Forward Ports" for your
device or ask the ETHStaker community.

Would you like to retry?
'''                 ),
                    buttons=[
                        ('Retry', 1),
                        ('Skip', 2),
                        ('Quit', False)
                    ]
                ).run()

                if not result:
                    return result
                
                if result == 1:
                    time.sleep(5)
                    continue
            
                if result == 2:
                    break

            else:
                all_ports_opened = True

        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to StakeHouse Port Checker',
                text=(
f'''
We could not connect to StakeHouse Port Checker server. Here are some
details for this last test we tried to perform:

URL: {STAKEHOUSE_PORT_CHECKER_URL}
Method: GET
Parameters: {json.dumps(params)}
Exception: {exception}

Would you like to retry?
'''             ),
                buttons=[
                    ('Retry', 1),
                    ('Skip', 2),
                    ('Quit', False)
                ]
            ).run()

            if not result:
                return result
            
            if result == 1:
                time.sleep(5)
                continue
        
            if result == 2:
                break
    
    if all_ports_opened:
        print('Open ports are configured correctly.')
    else:
        print('We could not confirm that open ports are configured correctly.')

    time.sleep(5)
    return True

def select_keys_directory(network):
    # Prompt the user for a directory that contains keys he generated already for the selected
    # network

    valid_keys_directory = False
    entered_directory = None
    input_canceled = False

    while not valid_keys_directory:
        not_valid_msg = ''
        if entered_directory is not None:
            not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>not a valid keys directory</b>. Please make sure to enter a
valid keys directory.</style>'''
            )

        entered_directory = input_dialog(
            title='Keys directory',
            text=(HTML(
f'''
Please enter the directory in which we can find the keys you generated. It
should include all the files that the eth2.0-deposit-cli tool created
including:

- deposit_data(...).json
- keystore-(...).json

When creating your keys offline or elsewhere, make sure you select the
correct network: {network.capitalize()}

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

        if not entered_directory:
            input_canceled = True
            break
    
        entered_directory = Path(entered_directory)

        if not entered_directory.is_dir():
            continue
        
        generated_keys = search_for_generated_keys(entered_directory)
        if (
            generated_keys['deposit_data_path'] is not None and
            len(generated_keys['keystore_paths']) > 0):
            valid_keys_directory = True

    if input_canceled:
        return ''

    return entered_directory

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