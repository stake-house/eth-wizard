import httpx
import json
import os

from urllib.parse import urlparse

from eth2validatorwizard.constants import *

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import radiolist_dialog, button_dialog, input_dialog
from prompt_toolkit.shortcuts.dialogs import _return_none, _create_app

from typing import Optional

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

from prompt_toolkit.widgets import (
    Button,
    Dialog,
    Label,
    TextArea,
    ValidationToolbar,
)

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
            (NETWORK_PYRMONT, "Pyrmont"),
            (NETWORK_PRATER, "Prater")
        ],
        ok_text='Use this',
        cancel_text='Quit'
    ).run()

    return result

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
        return all([result.scheme, result.netloc, result.path])
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