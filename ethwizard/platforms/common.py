from __future__ import annotations

import httpx
import json
import os
import time
import humanize
import asyncio
import re

from rfc3986 import urlparse, builder as urlbuilder

from datetime import timedelta

from dataclasses import dataclass

from pathlib import Path

from ethwizard.constants import *

from ethwizard.utils.CompactFIPS202 import Keccak_256

from asyncio import get_event_loop

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import radiolist_dialog, button_dialog, input_dialog
from prompt_toolkit.shortcuts.dialogs import _return_none, _create_app

from typing import Optional, Callable, List

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

from yaml import safe_load
from secrets import choice


@dataclass
class Step():
    step_id: str
    display_name: str
    exc_function: Callable[[Step, dict, StepSequence], dict]


@dataclass
class StepSequence():
    steps: List[Step]
    save_state: Callable[[str, dict], bool]
    context_factory: Optional[Callable[[], dict]] = None
    _steps_index: Optional[dict] = None

    def run_from_start(self, context: Optional[dict] = None) -> bool:
        if self.steps is None or len(self.steps) == 0:
            return False
        
        return self._run_from_index(0, context)

    def run_from_step(self, step_id: str, context: Optional[dict] = None) -> bool:
        if self._steps_index is None:
            self._build_steps_index()
        
        if step_id not in self._steps_index:
            return False
        
        step_index = self._steps_index[step_id]

        return self._run_from_index(step_index, context)
    
    def get_step(self, step_id: str) -> Optional[Step]:
        if self._steps_index is None:
            self._build_steps_index()
        
        if step_id not in self._steps_index:
            return None

        step_index = self._steps_index[step_id]

        return self.steps[step_index]

    def _build_steps_index(self):
        self._steps_index = {}

        if self.steps is None:
            return
        
        for index, step in enumerate(self.steps):
            self._steps_index[step.step_id] = index

    def _run_from_index(self, step_index: int, context: Optional[dict] = None) -> bool:
        if self.steps is None or len(self.steps) == 0:
            return False
        
        if step_index < 0 or step_index >= len(self.steps):
            return False
        
        if context is None:
            if self.context_factory is None:
                context = {}
            else:
                context = self.context_factory()

        for index in range(step_index, len(self.steps)):
            current_step = self.steps[index]
            self.save_state(current_step.step_id, context)

            context = current_step.exc_function(current_step, context, self)

        self.save_state(WIZARD_COMPLETED_STEP_ID, context)

        return True

def is_completed_state(state):
    return (
        state is not None and
        'step' in state and
        'context' in state and
        state['step'] == WIZARD_COMPLETED_STEP_ID)

def select_network(log):
    # Prompt for the selection on which network to perform the installation

    unknown_joining_queue = '(No join queue information found)'

    network_queue_info = {
        NETWORK_MAINNET: unknown_joining_queue,
        NETWORK_GOERLI: unknown_joining_queue
    }

    headers = {
        'accept': 'application/json'
    }

    async def network_joining_validators(network):
        async with httpx.AsyncClient() as client:
            beaconcha_in_queue_query_url = (
                BEACONCHA_IN_URLS[network] + BEACONCHA_VALIDATOR_QUEUE_API_URL)
            try:
                response = await client.get(beaconcha_in_queue_query_url, headers=headers,
                    follow_redirects=True)
            except httpx.RequestError as exception:
                log.error(f'Exception: {exception} while querying beaconcha.in.')
                return None

            if response.status_code != 200:
                log.error(f'Status code: {response.status_code} while querying beaconcha.in.')
                return None

            response_json = response.json()

            if (
                response_json and
                'data' in response_json and
                'beaconchain_entering' in response_json['data']):
                validators_entering = int(response_json['data']['beaconchain_entering'])
                waiting_td = timedelta(days=validators_entering / 900.0)

                queue_info = (
                    f'({validators_entering} validators waiting to join '
                    f'[{humanize.naturaldelta(waiting_td)}])'
                )
                return network, queue_info
            
        return None

    async_tasks = []

    for network in network_queue_info.keys():
        async_tasks.append(network_joining_validators(network))
    
    loop = asyncio.get_event_loop()
    results = loop.run_until_complete(asyncio.gather(*async_tasks))

    for result in results:
        if result is None:
            continue
        network, queue_info = result
        network_queue_info[network] = queue_info

    result = radiolist_dialog(
        title='Network selection',
        text=(
'''
This wizard supports installing and configuring software for various
Ethereum networks. Mainnet is the main network with real value. The others
are mostly for testing and they do not use anything of real value.

Joining a beacon chain network as a validator can take extra time if many
validators are trying to join at the same time. The amount of validators in
the join queue and the estimated time is displayed below for each network.

For which network would you like to perform this installation?

* Press the tab key to switch between the controls below
'''
        ),
        values=[
            (NETWORK_MAINNET, f'{NETWORK_LABEL[NETWORK_MAINNET]} {network_queue_info[NETWORK_MAINNET]}'),
            (NETWORK_GOERLI, f'{NETWORK_LABEL[NETWORK_GOERLI]} {network_queue_info[NETWORK_GOERLI]}')
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

Execution node: {ports['eth1']} (TCP/UDP)
Consensus beacon node: {ports['eth2_bn']} (TCP/UDP)

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
                title='Custom port for execution node',
                text=(HTML(
f'''
Please enter your custom port for your execution node:

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
                title='Custom port for consensus beacon node',
                text=(HTML(
f'''
Please enter your custom port for your consensus beacon node:

The default port is {ports['eth2_bn']} (TCP/UDP)

That port number should be greater than 1024 and lower than 65535. It
should also be different from the one you choose for execution node.

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

def select_consensus_checkpoint_provider(network, log):
    # Prompt the user for consensus checkpoint provider (weak subjectivity checkpoint)
    
    buttons = [
        ('Community', 1),
        ('Custom', 2),
        ('Skip', 3),
        ('Quit', False)
    ]

    initial_state_url = None

    while initial_state_url is None:

        result = button_dialog(
                title='Adding consensus checkpoint provider',
                text=(HTML(
f'''
Having a consensus checkpoint provider is highly recommended for your
beacon node. It makes it possible to get a fully synced beacon in just a
few minutes compared to having to wait hours or days.

We can select a random community checkpoint sync endpoint for you from
https://eth-clients.github.io/checkpoint-sync-endpoints/ .

If you have access to a custom beacon node, you can enter your own URL to
that beacon node with the custom option. That beacon node should be on the
<b>{NETWORK_LABEL[network]}</b> Ethereum network.

Do you want add a consensus checkpoint provider?
'''             )),
                buttons=buttons
            ).run()
        
        if not result:
            # Quit
            return result
        
        elif result == 3:
            # Skip
            return ''
        elif result == 1:
            # Community

            # Download YAML file with all the endpoints
            checkpoint_yaml_file = COMMUNITY_CHECKPOINT_SYNC_YAML[network]
            checkpoint_endpoints = []

            try:
                response = httpx.get(checkpoint_yaml_file, follow_redirects=True)

                if response.status_code != 200:
                    log.error(f'Checkpoint YAML file returned an unexpected status code from {checkpoint_yaml_file}: {response.status_code}')
                    return False

                checkpoint_endpoints = safe_load(response.text)
                
            except httpx.RequestError as exception:
                log.error(f'Exception during request to download checkpoint YAML file from {checkpoint_yaml_file}: {exception}')
                return False

            if len(checkpoint_endpoints) <= 0:
                log.error(f'No endpoint found in checkpoint YAML file from {checkpoint_yaml_file}')
                return False
            
            log.info(f'{len(checkpoint_endpoints)} checkpoint sync endpoints to choose from.')

            is_invalid = True

            # Select a random endpoint from the YAML file
            while is_invalid:
                if len(checkpoint_endpoints) <= 0:
                    log.error(f'No suitable checkpoint sync endpoint left to choose from.')
                    return False
                endpoint_details = choice(checkpoint_endpoints)
                checkpoint_endpoints.remove(endpoint_details)

                endpoint_name = endpoint_details.get('name', UNKNOWN_VALUE)
                endpoint_url = endpoint_details.get('endpoint', '')

                log.info(f'Random endpoint selected: {endpoint_name} at {endpoint_url}')

                if endpoint_url == '':
                    log.error(f'Endpoint does not have an URL. Skipping.')
                    continue

                # Test if the endpoint works, select another one if not
                is_invalid = not beacon_node_url_validator(network, endpoint_url, log)
                if not is_invalid:
                    initial_state_url = endpoint_url

        elif result == 2:
            # Custom
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
                    title='Consensus checkpoint provider using custom URL',
                    text=(HTML(
f'''
Please enter your beacon node URL:

It usually starts with 'https://' and it should point to the root of a
running beacon node on the <b>{NETWORK_LABEL[network]}</b> Ethereum network that supports the
Ethereum Beacon Node API. It should implement these endpoints:

- {BN_DEPOSIT_CONTRACT_URL}
- {BN_FINALIZED_STATE_URL}

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

                if not entered_url:
                    input_canceled = True
                    break
            
                initial_state_url = entered_url
                
                valid_url = beacon_node_url_validator(network, initial_state_url, log)

            if input_canceled:
                # User clicked the cancel button
                continue

    return initial_state_url

def beacon_node_url_validator(network, url, log):
    # Return true if this is a beacon chain endpoint for the network

    if not uri_validator(url):
        return False
    
    base_url = urlbuilder.URIBuilder.from_uri(url)
    deposit_contract_url = base_url.add_path(BN_DEPOSIT_CONTRACT_URL).finalize().unsplit()

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = httpx.get(deposit_contract_url, headers=headers, follow_redirects=True)

        if response.status_code != 200:
            log.error(f'Beacon node returned an unexpected status code: {response.status_code}')
            return False
        
        response_json = response.json()

        if not response_json:
            log.error(f'Unexpected response from beacon node.')
            return False

        if (
            'data' not in response_json or
            'chain_id' not in response_json['data'] or
            'address' not in response_json['data']
        ):
            log.error('Unexpected response from beacon node.')
            return False
        
        chain_id = response_json['data']['chain_id']
        deposit_contract = response_json['data']['address']

        if int(chain_id) != BN_CHAIN_IDS[network]:
            log.error(f'Unexpected chain_id ({chain_id}) from beacon node. We expected another '
                f'value ({BN_CHAIN_IDS[network]}) for this network ({network}).')
            return False
        
        if deposit_contract.lower() != BN_DEPOSIT_CONTRACTS[network].lower():
            log.error(f'Unexpected deposit contract address ({deposit_contract}) from beacon '
                f'node. We expected another value ({BN_DEPOSIT_CONTRACTS[network]}) for this '
                f'network ({network}).')
            return False
        
    except httpx.RequestError as exception:
        log.error(f'Exception during request to beacon node: {exception}')
        return False

    return True

def select_eth1_fallbacks(network):
    # Prompt the user for ethereum execution fallback nodes
    eth1_fallbacks = []

    add_more_fallbacks = True
    eth1_network_name = ETH1_NETWORK_NAME[network]
    eth1_network_chainid = ETH1_NETWORK_CHAINID[network]

    while add_more_fallbacks:
        skip_done_button_label = 'Skip'
        if len(eth1_fallbacks) > 0:
            skip_done_button_label = 'Done'

        result = button_dialog(
            title='Adding execution fallback nodes',
            text=(
f'''
Having Ethereum execution fallback nodes is highly recommended for your
beacon node. It will provide execution data even when your Geth client is
out of sync, in maintenance or when it is down.

You can find a good list of public ethereum execution nodes available on:

https://ethereumnodes.com/

We recommend creating a free account with at least Infura and Alchemy and
adding their endpoints as your Ethereum execution fallback nodes. Make sure
to choose the correct Ethereum network in your project: {eth1_network_name} .

{len(eth1_fallbacks)} execution fallback node(s) added so far.

Do you want add one or more execution fallback node?
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
                title='New execution fallback node',
                text=(HTML(
f'''
Please enter your execution fallback endpoint:

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
            response = httpx.post(eth1_fallback, json=request_json, headers=headers,
                follow_redirects=True)
        except httpx.RequestError as exception:
            result = button_dialog(
                title='Cannot connect to execution fallback endpoint',
                text=(
f'''
We could not connect to this execution fallback endpoint. Here are
some details for this last test we tried to perform:

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
                title='Cannot connect to execution fallback endpoint',
                text=(
f'''
We could not connect to this execution fallback endpoint. Here are some
details for this last test we tried to perform:

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
            # We could not get a proper result from the Ethereum execution endpoint
            result = button_dialog(
                title='Unexpected response from execution fallback endpoint',
                text=(
f'''
We received an unexpected response from this execution fallback endpoint.
Here are some details for this last test we tried to perform:

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
                title='Unexpected chain id from execution fallback endpoint',
                text=(
f'''
We received an unexpected chain id response from this execution fallback
endpoint. Here are some details for this:

Expected chain id: {eth1_network_chainid}
Received chain id: {eth1_fallback_chainid}

Did you select an execution endpoint with the proper network? It should be the
ethereum network: {eth1_network_name}

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
    # Search for keys

    deposit_data_path = None
    keystore_paths = []
    password_paths = []

    validator_keys_path = Path(validator_keys_path)

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
        'validator_keys_path': str(validator_keys_path),
        'deposit_data_path': deposit_data_path,
        'keystore_paths': keystore_paths,
        'password_paths': password_paths
    }

def get_bc_validator_deposits(network, public_keys, log):
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
            response = httpx.get(bc_api_query_url, headers=headers, follow_redirects=True)
        except httpx.RequestError as exception:
            log.error(f'Exception {exception} when trying to get {bc_api_query_url}')

            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue

        if response.status_code != 200:
            log.error(f'Error code {response.status_code} when trying to get {bc_api_query_url}')
            
            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue
        
        response_json = response.json()

        if (
            'status' not in response_json or
            response_json['status'] != 'OK' or
            'data' not in response_json
            ):
            log.error(f'Unexpected response data or structure from {bc_api_query_url}: '
                f'{response_json}')
            
            retry_index = retry_index + 1
            log.info(f'We will retry in {retry_delay} seconds (retry index = {retry_index})')
            time.sleep(retry_delay)
            continue
        
        keep_retrying = False
    
    if keep_retrying:
        log.error(f'We failed to get the validator deposits from the beaconcha.in API after '
            f'{retry_count} retries.')
        time.sleep(5)
        return False
    
    validator_deposits = response_json['data']
    # beaconcha.in API does not return a list for a single validator so
    # we make it a list for ease of use
    if type(validator_deposits) is not list:
        validator_deposits = [validator_deposits]

    return validator_deposits

def test_open_ports(ports, log):
    # Test the selected ports to make sure they are opened and exposed to the internet

    params = {
        'ports': str(ports['eth1']) + ',' + str(ports['eth2_bn'])
    }

    requested_ports = {ports['eth1'], ports['eth2_bn']}

    all_ports_opened = False

    log.info('Checking for open ports...')

    while not all_ports_opened:
        try:
            log.info('Connecting to StakeHouse Port Checker...')
            response = httpx.get(STAKEHOUSE_PORT_CHECKER_URL, params=params,
                follow_redirects=True)

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
        log.info('Open ports are configured correctly.')
    else:
        log.warning('We could not confirm that open ports are configured correctly.')

    time.sleep(5)
    return True

def select_keys_directory(network):
    # Prompt the user for a directory that contains keys he generated already for the selected
    # network

    valid_keys_directory = False
    no_deposit_data_found = False
    entered_directory = None
    input_canceled = False

    while not valid_keys_directory:
        not_valid_msg = ''
        if no_deposit_data_found:
            not_valid_msg = (
'''

Your last input was a directory that did not include the deposit data file.
Please make sure to enter a directory that includes the deposit data file.'''
            )
        elif entered_directory is not None:
            not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>not a valid keys directory</b>. Please make sure to enter a
valid keys directory.</style>'''
            )
        
        no_deposit_data_found = False

        entered_directory = input_dialog(
            title='Keys directory',
            text=(HTML(
f'''
Please enter the directory in which we can find the keys you generated. It
should include all the files that the key tool created including:

- deposit_data(...).json
- keystore-(...).json

When creating your keys offline or elsewhere, make sure you select the
correct network: {NETWORK_LABEL[network]}

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

        if not entered_directory:
            input_canceled = True
            break
    
        tilde_index = entered_directory.find('~')
        if tilde_index != -1:
            entered_directory = entered_directory.replace('~', str(Path.home()), 1)

        entered_directory = Path(entered_directory)

        if not entered_directory.is_dir():
            continue
        
        generated_keys = search_for_generated_keys(entered_directory)

        if len(generated_keys['keystore_paths']) > 0:

            if generated_keys['deposit_data_path'] is None:

                result = button_dialog(
                    title='No deposit file found',
                    text=(
f'''
We could not find a deposit data file. This could be fine if you already
did your deposit. Make sure you are not importing keystore files that are
already being used by another running validator client.

If this is your first setup with these keystore files, we strongly suggest
you include your deposit data file along with your keystore files so we can
guide you better.

Would you like to retry with a directory that has your deposit data file?
'''             ),
                    buttons=[
                        ('Retry', 1),
                        ('Skip', 2),
                        ('Quit', False)
                    ]
                ).run()

                if not result:
                    return result
                
                if result == 2:
                    valid_keys_directory = True
                
                no_deposit_data_found = True

            else:
                valid_keys_directory = True

    if input_canceled:
        return ''

    return entered_directory

def select_fee_recipient_address():
    # Prompt the user for a fee recipient address
    
    valid_address = False
    entered_address = None
    input_canceled = False

    while not valid_address:
        not_valid_msg = ''
        if entered_address is not None:
            not_valid_msg = (
'''

<style bg="red" fg="black">Your last input was <b>not a valid Ethereum address</b>. Please make sure to enter
a valid Ethereum address.</style>'''
            )

        entered_address = input_dialog(
            title='Fee recipient address',
            text=(HTML(
f'''
Please enter an Ethereum address to be used as your fee recipient address.
Make sure you have control over this address. This is where the transaction
tips for your proposed blocks will go into.

* Press the tab key to switch between the controls below{not_valid_msg}
'''             ))).run()

        if not entered_address:
            input_canceled = True
            break

        if is_address(entered_address):
            valid_address = True

    if input_canceled:
        return ''
    
    if entered_address.lower()[:2] != '0x':
        entered_address = '0x' + entered_address

    return entered_address

def is_checksum_address(address):
    # Check for valid checksumed Ethereum address
    address = address.replace('0x', '').strip()
    address_hash = Keccak_256(address.lower().encode('utf-8')).hex()

    for i in range(0, 40):
        if ((int(address_hash[i], 16) > 7 and address[i].upper() != address[i]) or
                (int(address_hash[i], 16) <= 7 and address[i].lower() != address[i])):
            return False
    return True

def is_address(address):
    # Check for valide Ethereum address
    if not re.match(r'^(0x)?[0-9a-f]{40}$', address, flags=re.IGNORECASE):
        return False
    elif re.match(r'^(0x)?[0-9a-f]{40}$', address) or re.match(r'^(0x)?[0-9A-F]{40}$', address):
        return True
    else:
        return is_checksum_address(address)

def show_whats_next(network, public_keys):
    # Show what's next including wait time

    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    button_dialog(
        title='Installation completed',
        text=(
f'''
You just completed all the steps needed to become an active validator on
the {NETWORK_LABEL[network]} Ethereum network. {len(public_keys)} validator{'s' if len(public_keys) > 1 else ''} {'are' if len(public_keys) > 1 else 'is' } now running on this machine.

You can monitor your activation period and all the details about your
validator(s) on the beaconcha.in website at the following URL:

{beaconcha_in_url}

If you have any question or if you need additional support, make sure
to get in touch with the ethstaker community on:

* Discord: discord.io/ethstaker
* Reddit: reddit.com/r/ethstaker
'''     ),
        buttons=[
            ('Quit', False)
        ]
    ).run()

def show_public_keys(network, public_keys, log):
    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    newline = '\n'

    log.info(
f'''
eth-wizard completed!

Network: {NETWORK_LABEL[network]}
Number of validator(s): {len(public_keys)}

Make sure to note or save your public keys somewhere. Your validator public
key(s) are:
{newline.join(public_keys)}

Make sure to check the beaconcha.in website for more details about your
validator(s):
{beaconcha_in_url}
''' )

def test_context_variable(context, variable, log):
    if variable not in context:
        log.error(f'We expected {variable} to be in the context at this point but we could not '
            f'find it. Here is the full context: {json.dumps(context)}')
        return False
    
    return True

def get_geth_running_version(log):
    # Get the running version for Geth

    log.info('Getting Geth running version...')

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
        log.error(f'Cannot connect to Geth. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_geth_jsonrpc_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'result' not in response_json:
        log.error(f'Unexpected JSON response from {local_geth_jsonrpc_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['result']

    # Version agent should look like: Geth/v1.10.12-stable-6c4dc6c3/linux-amd64/go1.17.2
    result = re.search(r'Geth/v(?P<version>[^-/]+)(-(?P<stable>[^-/]+))?(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Geth version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Geth running version is {running_version}')

    return running_version

def get_geth_latest_version(log):
    # Get the latest stable version for Geth, potentially not available yet for update

    log.info('Getting Geth latest version...')

    geth_gh_release_url = GITHUB_REST_API_URL + GETH_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(geth_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Geth. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Geth. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Geth.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Geth version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Geth latest version is {latest_version}')

    return latest_version