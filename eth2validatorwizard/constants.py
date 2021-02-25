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