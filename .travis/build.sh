#!/bin/bash -x
set -e

python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt -r tests/requirements.txt

python3 setup.py install
pytest -vvv tests/
