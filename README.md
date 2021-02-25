# eth2-validator-wizard
An Eth2 validator installation wizard meant to guide anyone through the different steps to become a fully functional validator on the Ethereum 2.0 network. It will install and configure all the software needed to become a validator.

## Disclaimer

The eth2-validator-wizard is not ready to be used in the real world yet. It is still in development and it is subject to radical changes. It can still have major and important issues. DO NOT USE UNLESS YOU KNOW WHAT YOU ARE DOING! This disclaimer will be removed once we believe it is ready for the general population.

## Goals

* Simple to use
* Minimal
* Mostly automated
* For Ubuntu 20.04 using Lighthouse and Geth
* No prerequisite needed
* Internally simple to read, understand and modify
* Interruptible and resumable
* Launched using a simple command line that bootstraps everything
* Self-updating to the latest version on launch

## How to use

This procedure is going to evolve over time (it's going to get much easier to launch), but you can use something like this to test and start the wizard:

```
sudo apt update
sudo apt install python3-pip
git clone https://github.com/remyroy/eth2-validator-wizard.git
cd eth2-validator-wizard
sudo pip3 install -r requirements.txt
sudo python3 -m eth2validatorwizard
```

## Support

If you have any question or if you need additional support, make sure to get in touch with the ethstaker community on:

* Discord: [discord.gg/e84CFep](https://discord.gg/e84CFep)
* Reddit: [reddit.com/r/ethstaker](https://www.reddit.com/r/ethstaker/)

## Credits

Based on [Somer Esat's guide](https://someresat.medium.com/guide-to-staking-on-ethereum-2-0-ubuntu-lighthouse-41de20513b12).

## License

This project is licensed under the terms of [the MIT license](LICENSE).