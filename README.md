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
# Set the URL to run the API at
export SIGSERV_URL="127.0.0.1:5000" # The default
# Start the server (preferably in another term, or in background)
python3 tests/start_sigserver.py
# Run the test suite
pytest -vvv tests/ -n4
```
