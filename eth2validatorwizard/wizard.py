from prompt_toolkit.shortcuts import button_dialog

def run():
    # Main entry point for the wizard.

    if not show_welcome():
        # User asked to quit, let's end here
        quit()

    self_update()

    # Explain overall process

    print('Ended')

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
'''),
        buttons=[
            ('Start', True),
            ('Quit', False)
        ]
    ).run()

    return result


def self_update():
    # TODO: Check for a new version of the wizard and self-update if needed

    pass