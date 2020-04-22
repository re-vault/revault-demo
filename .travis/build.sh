#!/bin/bash -x
set -e

mkdir -p dependencies/bin || true

if [ ! -f dependencies/bin/bitcoind ]; then
    wget https://bitcoin.org/bin/bitcoin-core-0.19.1/bitcoin-0.19.1-x86_64-linux-gnu.tar.gz
    tar -xzf bitcoin-0.19.1-x86_64-linux-gnu.tar.gz
    mv bitcoin-0.19.1/bin/* dependencies/bin
    rm -rf bitcoin-0.19.1-x86_64-linux-gnu.tar.gz bitcoin-0.19.1
fi

PATH=$PATH:$(pwd)/dependencies/bin

python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt -r tests/requirements.txt

python3 setup.py install
pytest -vvv tests/test_transactions.py
pytest -vvv tests/test_vault.py
