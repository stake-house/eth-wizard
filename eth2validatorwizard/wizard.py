import os
import subprocess

from eth2validatorwizard.constants import *

from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog

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

    # TODO: Detect if installation is already started

    if not explain_overview():
        # User asked to quit
        quit()

    # TODO: Check for open ports
    # TODO: Check for disk size
    # TODO: Check for disk speed

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit()

    if not install_geth(selected_network):
        # User asked to quit
        quit()

    # Install Geth
    # Start Geth
    # Check for syncing on Geth

    # Install Lighthouse Beacon
    # Start & Enable Lighthouse Beacon
    # Check for syncing on Lighthouse Beacon

    # Generate Keys
    # Import keystore files for Validator
    # Install Lighthouse Validator
    # Start & Enable Lighthouse Validator
    # Check for good connection between Lighthouse Validator and Lighthouse Beacon

    # Deposit via launchpad

    # TODO: Monitor

    print('Ended normally with network', selected_network)

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
and good internet.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    # Install Geth from PPA
    subprocess.run([
        'add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
    subprocess.run([
        'apt', 'update'])
    subprocess.run([
        'apt', 'install', 'geth'])
    
    # Setup Geth user and directory
    subprocess.run([
        'useradd', '--no-create-home', '--shell', '/bin/false', 'goeth'])
    subprocess.run([
        'mkdir', '-p', '/var/lib/goethereum'])
    subprocess.run([
        'chown', '-R', 'goeth:goeth', '/var/lib/goethereum'])
    
    # Setup Geth systemd service
    with open('/etc/systemd/system/geth.service', 'w') as service_file:
        service_file.write(GETH_SERVICE_DEFINITION[network])
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', 'geth'])
    subprocess.run([
        'systemctl', 'enable', 'geth'])

    