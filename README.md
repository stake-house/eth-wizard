# eth-wizard
An Ethereum validator installation wizard meant to guide anyone through the different steps to become a fully functional validator on the Ethereum network. It will install and configure all the software needed to become a validator. It will test your installation. It will help you avoid the common pitfalls.

This project is part of [the larger StakeHouse community](https://github.com/stake-house/stakehouse).

## Disclaimer

The eth-wizard should be stable enough to be used by everyone. It was never audited and it might still have some issues. Support is offered through [the ETHStaker community](https://ethstaker.cc/).

## Goals

* Simple to use
* Minimal
* Mostly automated
* For Ubuntu 20.04 or 22.04 using Lighthouse and Geth
* For Windows 10 using Teku and Geth
* No prerequisite needed
* Internally simple to read, understand and modify
* Interruptible and resumable
* Launched using a simple command line that bootstraps everything
* Self-updating to the latest version on launch

## How to use

### On Ubuntu 20.04 or 22.04

You can use something like this in a terminal, to start the wizard:

```
wget https://github.com/stake-house/eth-wizard/releases/download/v0.8.2/ethwizard-0.8.2.pyz && sudo python3 ethwizard-0.8.2.pyz
```

### On Windows 10

Please note that some antivirus software might detect the wizard binary as a threat and delete it or prevent its execution.

Download and run [the wizard binary](https://github.com/stake-house/eth-wizard/releases/download/v0.8.2/ethwizard-0.8.2.exe)

As an alternative, you can download and install [a recent version of Python](https://www.python.org/downloads/) (make sure to select the option for file associations which is included in the default *Install Now* option), download [the latest pyz bundle](https://github.com/stake-house/eth-wizard/releases/download/v0.8.2/ethwizard-0.8.2.pyz) and double-click on it. This alternative is less likely to trigger your antivirus software.

## Demonstration

Here is a demonstration of eth-wizard on Ubuntu 20.04:

[![eth-wizard demo (v0.7.2) for Ubuntu 20.04](https://img.youtube.com/vi/2bnCO5Cujn0/0.jpg)](https://youtu.be/2bnCO5Cujn0)

## Support

If you have any question or if you need additional support, make sure to get in touch with the ETHStaker community on:

* Discord: [discord.io/ethstaker](https://discord.io/ethstaker)
* Reddit: [reddit.com/r/ethstaker](https://www.reddit.com/r/ethstaker/)

## Credits

Based on [Somer Esat's guide](https://github.com/SomerEsat/ethereum-staking-guide).

## License

This project is licensed under the terms of [the MIT license](LICENSE).
