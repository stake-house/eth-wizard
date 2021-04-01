GITHUB_REST_API_URL = 'https://api.github.com'
GITHUB_API_VERSION = 'application/vnd.github.v3+json'

LIGHTHOUSE_LATEST_RELEASE = '/repos/sigp/lighthouse/releases/latest'
LIGHTHOUSE_PRIME_PGP_KEY_ID = '15E66D941F697E28F49381F426416DC3F30674B0'

ETH2_DEPOSIT_CLI_LATEST_RELEASE = '/repos/ethereum/eth2.0-deposit-cli/releases/latest'

NETWORK_MAINNET = 'mainnet'
NETWORK_PYRMONT = 'pyrmont'
NETWORK_PRATER = 'prater'

DEFAULT_GETH_PORT = 30303
DEFAULT_LIGHTHOUSE_BN_PORT = 9000

SPEEDTEST_SCRIPT_URL = 'https://raw.githubusercontent.com/sivel/speedtest-cli/master/speedtest.py'

MIN_AVAILABLE_DISK_SPACE_GB = 900.0

MIN_DOWN_MBS = 5.0
MIN_UP_MBS = 5.0

LAUNCHPAD_URLS = {
    NETWORK_MAINNET: 'https://launchpad.ethereum.org',
    NETWORK_PYRMONT: 'https://pyrmont.launchpad.ethereum.org',
    NETWORK_PRATER: 'https://prater.launchpad.ethereum.org'
}

BEACONCHA_IN_URLS = {
    NETWORK_MAINNET: 'https://beaconcha.in',
    NETWORK_PYRMONT: 'https://pyrmont.beaconcha.in',
    NETWORK_PRATER: 'https://prater.beaconcha.in'
}

NETWORK_CURRENCY = {
    NETWORK_MAINNET: 'ETH',
    NETWORK_PYRMONT: 'GöETH',
    NETWORK_PRATER: 'GöETH',
}

ETH1_NETWORK_NAME = {
    NETWORK_MAINNET: 'Mainnet',
    NETWORK_PYRMONT: 'Görli',
    NETWORK_PRATER: 'Görli'
}

ETH1_NETWORK_CHAINID = {
    NETWORK_MAINNET: 1,
    NETWORK_PYRMONT: 5,
    NETWORK_PRATER: 5
}

BEACONCHA_VALIDATOR_DEPOSITS_API_URL = '/api/v1/validator/{indexOrPubkey}/deposits'

ETHEREUM_APT_SOURCE_URL = 'http://ppa.launchpad.net/ethereum/ethereum/ubuntu'

GETH_SERVICE_DEFINITION = {
    NETWORK_MAINNET: (
'''
[Unit]
Description=Go Ethereum Client - Geth (Mainnet)
After=network.target
Wants=network.target

[Service]
User=goeth
Group=goeth
Type=simple
Restart=always
RestartSec=5
ExecStart=geth --cache 2048 --syncmode=snap --http --datadir /var/lib/goethereum --metrics --metrics.expensive --pprof

[Install]
WantedBy=default.target
'''),
    NETWORK_PYRMONT: (
'''
[Unit]
Description=Go Ethereum Client - Geth (Görli)
After=network.target
Wants=network.target

[Service]
User=goeth
Group=goeth
Type=simple
Restart=always
RestartSec=5
ExecStart=geth --goerli --syncmode=snap --http --datadir /var/lib/goethereum --metrics --metrics.expensive --pprof

[Install]
WantedBy=default.target
'''),
    NETWORK_PRATER: (
'''
[Unit]
Description=Go Ethereum Client - Geth (Görli)
After=network.target
Wants=network.target

[Service]
User=goeth
Group=goeth
Type=simple
Restart=always
RestartSec=5
ExecStart=geth --goerli --syncmode=snap --http --datadir /var/lib/goethereum --metrics --metrics.expensive --pprof

[Install]
WantedBy=default.target
''')
}

LIGHTHOUSE_BN_SERVICE_DEFINITION = {
    NETWORK_MAINNET: (
'''
[Unit]
Description=Lighthouse Eth2 Client Beacon Node (Mainnet)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=lighthousebeacon
Group=lighthousebeacon
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse bn --network mainnet --datadir /var/lib/lighthouse --staking --eth1-endpoints {eth1endpoints} --validator-monitor-auto --metrics

[Install]
WantedBy=multi-user.target
'''),
    NETWORK_PYRMONT: (
'''
[Unit]
Description=Lighthouse Eth2 Client Beacon Node (Pyrmont)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=lighthousebeacon
Group=lighthousebeacon
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse bn --network pyrmont --datadir /var/lib/lighthouse --staking --eth1-endpoints {eth1endpoints} --validator-monitor-auto --metrics

[Install]
WantedBy=multi-user.target
'''),
    NETWORK_PRATER: (
'''
[Unit]
Description=Lighthouse Eth2 Client Beacon Node (Prater)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=lighthousebeacon
Group=lighthousebeacon
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse bn --network prater --datadir /var/lib/lighthouse --staking --eth1-endpoints {eth1endpoints} --validator-monitor-auto --metrics

[Install]
WantedBy=multi-user.target
''')
}

LIGHTHOUSE_VC_SERVICE_DEFINITION = {
    NETWORK_MAINNET: (
'''
[Unit]
Description=Lighthouse Eth2 Client Validator Client (Mainnet)
Wants=network-online.target
After=network-online.target

[Service]
User=lighthousevalidator
Group=lighthousevalidator
Type=simple
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse vc --network mainnet --datadir /var/lib/lighthouse --metrics

[Install]
WantedBy=multi-user.target
'''),
    NETWORK_PYRMONT: (
'''
[Unit]
Description=Lighthouse Eth2 Client Validator Client (Pyrmont)
Wants=network-online.target
After=network-online.target

[Service]
User=lighthousevalidator
Group=lighthousevalidator
Type=simple
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse vc --network pyrmont --datadir /var/lib/lighthouse --metrics

[Install]
WantedBy=multi-user.target
'''),
    NETWORK_PRATER: (
'''
[Unit]
Description=Lighthouse Eth2 Client Validator Client (Prater)
Wants=network-online.target
After=network-online.target

[Service]
User=lighthousevalidator
Group=lighthousevalidator
Type=simple
Restart=always
RestartSec=5
ExecStart=/usr/local/bin/lighthouse vc --network prater --datadir /var/lib/lighthouse --metrics

[Install]
WantedBy=multi-user.target
''')
}