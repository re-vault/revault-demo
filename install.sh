set -xe

if ! test -d venv;then
    python3 -m venv venv
fi
. venv/bin/activate
pip install -r requirements.txt

# Fetch bitcoinlib with CSV support
git clone https://github.com/petertodd/python-bitcoinlib && cd python-bitcoinlib
git remote add kanzure https://github.com/kanzure/python-bitcoinlib && git fetch kanzure
git checkout -b kanzure/bip112-checksequenceverify-opcode
python3 setup.py install && cd .. && rm -rf python-bitcoinlib

set +xe
