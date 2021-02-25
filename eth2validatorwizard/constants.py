GITHUB_REST_API_URL = 'https://api.github.com'
GITHUB_API_VERSION = 'application/vnd.github.v3+json'

LIGHTHOUSE_LATEST_RELEASE = '/repos/sigp/lighthouse/releases/latest'
LIGHTHOUSE_PRIME_PGP_KEY_ID = '15E66D941F697E28F49381F426416DC3F30674B0'

NETWORK_MAINNET = 'mainnet'
NETWORK_PYRMONT = 'pyrmont'

LAUNCHPAD_URLS = {
    NETWORK_MAINNET: 'https://launchpad.ethereum.org/',
    NETWORK_PYRMONT: 'https://pyrmont.launchpad.ethereum.org/'
}

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
ExecStart=geth --cache 2048 --http --datadir /var/lib/goethereum --metrics --metrics.expensive --pprof

[Install]
WantedBy=default.target
'''),
    NETWORK_PYRMONT: (
'''
[Unit]
Description=Go Ethereum Client - Geth (Pyrmont)
After=network.target
Wants=network.target

[Service]
User=goeth
Group=goeth
Type=simple
Restart=always
RestartSec=5
ExecStart=geth --goerli --http --datadir /var/lib/goethereum --metrics --metrics.expensive --pprof

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
ExecStart=/usr/local/bin/lighthouse bn --network mainnet --datadir /var/lib/lighthouse --staking --eth1-endpoints http://127.0.0.1:8545 --validator-monitor-auto --metrics

[Install]
WantedBy=multi-user.target
'''),
    NETWORK_PYRMONT: (
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
ExecStart=/usr/local/bin/lighthouse bn --network pyrmont --datadir /var/lib/lighthouse --staking --eth1-endpoints http://127.0.0.1:8545 --validator-monitor-auto --metrics

[Install]
WantedBy=multi-user.target
''')
}