We use `pytest` as the testing framework, and some (a lot) of the fixtures and utilities
have been taken directly from the [C-lightning test framework](https://github.com/ElementsProject/lightning/tree/master/contrib/pyln-testing) and adapted.

Two main files for the tests, [test_transactions](test_transactions.py) which directly
test the transaction-creation functions, and [test_vault](test_vault.py) which tests the
functionalities of the wallet in action.

To run the tests, from the root of the repository:
```
# Install the revault dependencies
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
# Install revault
python3 setup.py install
# Install the tests dependencies
pip install -r tests/requirements.txt
# Run the test suite
pytest -vvv tests/
```
The tests parallelization can throw spurious errors due to the bitcoind RPC proxy..
