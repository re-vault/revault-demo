# vaultaic

Vaultaic is an Open Source (WIP) demo implementation of a multiparty vault
architecture designed by [Chainsmiths](http://chainsmiths.com) for the needs of
[NOIA](http://www.noiacapital.com/).

## Running the tests

```
# Install the vaultaic dependencies
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
# Install vaultaic
python3 setup.py install
# Install the tests dependencies
pip install -r tests/requirements.txt
pytest -vvv tests/ -n4
```

Some tests need a non-pytest-fixture Flask instance and will be skipped by the
above command, to run them:
```
# Start regtest, say the 5th bitcoind is the serv's bitcoind
start_regtest 5
# Start the signature server
. tests/start_sigserver regtest/bcdir5/bitcoin.conf
# Run the test suite
pytest -vvv tests/ -n6
```
