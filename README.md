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
# Install the tests dependencies
pip install -r tests/requirements.txt
pytest -vvv tests/unit_tests.py -n4
```
