# eth-wizard

[![GitPOAP Badge](https://public-api.gitpoap.io/v1/repo/stake-house/eth-wizard/badge)](https://www.gitpoap.io/gh/stake-house/eth-wizard)

An Ethereum validator installation wizard meant to guide anyone through the different steps to become a fully functional validator on the Ethereum network. It will install and configure all the software needed to become a validator. It will test your installation. It will help you avoid the common pitfalls. It will help you maintain and keep your setup updated.

## Disclaimer

Eth-wizard should be stable enough to be used by everyone. It was never audited and it might still have some issues. Support is offered through [the EthStaker community](https://ethstaker.cc/).

## Goals

* Simple to use
* Mostly automated
* For Ubuntu 20.04, 22.04 or 24.04
* For Windows 10 or 11
* No prerequisite needed
* Internally simple to read, understand and modify
* Interruptible and resumable
* Launched using a simple command line that bootstraps everything
* Self-updating to the latest version on launch

## How to use

### On Ubuntu 20.04 or 22.04

You can use something like this in a terminal, to start the wizard:

```
wget https://github.com/stake-house/eth-wizard/releases/download/v0.9.16/ethwizard-0.9.16.pyz && sudo python3 ethwizard-0.9.16.pyz
```

### On Windows 10 on 11

Please note that some antivirus software might detect the wizard binary as a threat and delete it or prevent its execution.

Download and run [the ethwizard-0.9.16.exe binary](https://github.com/stake-house/eth-wizard/releases/download/v0.9.16/ethwizard-0.9.16.exe)

As an alternative, you can download and install [a recent version of Python](https://www.python.org/downloads/), make sure to install py launcher (it should be part of the default options), download [the ethwizard-0.9.16-win.pyz bundle](https://github.com/stake-house/eth-wizard/releases/download/v0.9.16/ethwizard-0.9.16-win.pyz) and double-click on it. This alternative is less likely to trigger your antivirus software.

### Maintenance

Simply run eth-wizard again after a successful installation to perform maintenance. In maintenance mode, eth-wizard can check for updates and install them as needed.

## Supported clients:

### Execution clients:

* Geth
* Nethermind

### Consensus clients:

* Lighthouse
* Nimbus
* Teku (Windows only)

## Demonstration

Here is a demonstration of eth-wizard on Ubuntu 20.04:

[![eth-wizard demo (v0.7.2) for Ubuntu 20.04](https://img.youtube.com/vi/2bnCO5Cujn0/0.jpg)](https://youtu.be/2bnCO5Cujn0)

## Support

If you have any question or if you need additional support, make sure to get in touch with the EthStaker community on:

* Discord: [dsc.gg/ethstaker](https://dsc.gg/ethstaker)
* Reddit: [reddit.com/r/ethstaker](https://www.reddit.com/r/ethstaker/)

## Financial support

If you would like to help and support eth-wizard, check out [our donation page](donation.md).

## Credits

Based on [Somer Esat's guide](https://github.com/SomerEsat/ethereum-staking-guide).

## License

This project is licensed under the terms of [the MIT license](LICENSE).
