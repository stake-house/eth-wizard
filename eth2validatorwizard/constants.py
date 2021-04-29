GITHUB_REST_API_URL = 'https://api.github.com'
GITHUB_API_VERSION = 'application/vnd.github.v3+json'

LIGHTHOUSE_LATEST_RELEASE = '/repos/sigp/lighthouse/releases/latest'
LIGHTHOUSE_PRIME_PGP_KEY_ID = '15E66D941F697E28F49381F426416DC3F30674B0'
TEKU_LATEST_RELEASE = '/repos/ConsenSys/teku/releases/latest'
PROMETHEUS_LATEST_RELEASE = '/repos/prometheus/prometheus/releases/latest'

ETH2_DEPOSIT_CLI_LATEST_RELEASE = '/repos/ethereum/eth2.0-deposit-cli/releases/latest'

NETWORK_MAINNET = 'mainnet'
NETWORK_PYRMONT = 'pyrmont'
NETWORK_PRATER = 'prater'

DEFAULT_GETH_PORT = 30303
DEFAULT_LIGHTHOUSE_BN_PORT = 9000
DEFAULT_TEKU_BN_PORT = 9000

SPEEDTEST_SCRIPT_URL = 'https://raw.githubusercontent.com/sivel/speedtest-cli/master/speedtest.py'

MIN_AVAILABLE_DISK_SPACE_GB = 900.0

MIN_SUSTAINED_K_READ_IOPS = 3.0
MIN_SUSTAINED_K_WRITE_IOPS = 1.0

MIN_DOWN_MBS = 4.5
MIN_UP_MBS = 4.5

CHOCOLATEY_DEFAULT_BIN_PATH = r'C:\ProgramData\chocolatey\bin'

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

GETH_SERVICE_DISPLAY_NAME = {
    NETWORK_MAINNET: 'Go Ethereum Client - Geth (Mainnet)',
    NETWORK_PYRMONT: 'Go Ethereum Client - Geth (Görli)',
    NETWORK_PRATER: 'Go Ethereum Client - Geth (Görli)'
}

GNUPG_DOWNLOAD_URL = 'https://www.gnupg.org/download/'

GETH_STORE_BUILDS_URL = 'https://gethstore.blob.core.windows.net/builds'
GETH_STORE_BUILDS_PARAMS = {
    'restype': 'container',
    'comp': 'list',
    'maxresults': 5000,
    'prefix': 'geth-'
}
GETH_BUILDS_BASE_URL = 'https://gethstore.blob.core.windows.net/builds/'

GETH_WINDOWS_PGP_KEY_ID = '9417309ED2A67EAC'
GETH_ARGUMENTS = {
    NETWORK_MAINNET: ['--cache', '2048', '--syncmode=snap', '--http', '--metrics', '--metrics.expensive', '--pprof'],
    NETWORK_PYRMONT: ['--goerli', '--syncmode=snap', '--http', '--metrics', '--metrics.expensive', '--pprof'],
    NETWORK_PRATER: ['--goerli', '--syncmode=snap', '--http', '--metrics', '--metrics.expensive', '--pprof']
}

WINDOWS_SERVICE_RUNNING = 'SERVICE_RUNNING'
WINDOWS_SERVICE_START_PENDING = 'SERVICE_START_PENDING'

ADOPTOPENJDK_11_API_URL = 'https://api.adoptopenjdk.net/v3/assets/feature_releases/11/ga'
ADOPTOPENJDK_11_API_PARAMs = {
    'jvm_impl': 'hotspot',
    'vendor': 'adoptopenjdk'
}

TEKU_SERVICE_DISPLAY_NAME = {
    NETWORK_MAINNET: 'Teku Eth2 Client (Mainnet)',
    NETWORK_PYRMONT: 'Teku Eth2 Client (Pyrmont)',
    NETWORK_PRATER: 'Teku Eth2 Client (Prater)'
}

TEKU_ARGUMENTS = {
    NETWORK_MAINNET: ['--network=mainnet', '--metrics-enabled', '--rest-api-enabled'],
    NETWORK_PYRMONT: ['--network=pyrmont', '--metrics-enabled', '--rest-api-enabled'],
    NETWORK_PRATER: ['--network=prater', '--metrics-enabled', '--rest-api-enabled']
}

PROMETHEUS_CONFIG_WINDOWS = (
'''
global:
  scrape_interval:     15s
  evaluation_interval: 15s

rule_files:
  # - "first.rules"
  # - "second.rules"

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['localhost:9090']
  - job_name: geth
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: /debug/metrics/prometheus
    scheme: http
    static_configs:
      - targets: ['localhost:6060']
  - job_name: teku
    scrape_timeout: 10s
    metrics_path: /metrics
    scheme: http
    static_configs:
      - targets: ['localhost:8008']
'''
)

PROMETHEUS_ARGUMENTS = ['--web.listen-address="127.0.0.1:9090"']

PROMETHEUS_SERVICE_DISPLAY_NAME = 'Prometheus systems monitoring'

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