"""
Most of the code here is stolen from C-lightning's test suite. This is surely
Rusty Russell or Christian Decker who wrote most of this (I'd put some sats on
cdecker), so credits to them ! (MIT licensed)
"""
from utils import BitcoinD, VaultFactory
from revault import SigServer

import logging
import os
import pytest
import shutil
import tempfile

__attempts = {}


@pytest.fixture(scope="session")
def test_base_dir():
    d = os.getenv("TEST_DIR", "/tmp")

    directory = tempfile.mkdtemp(prefix='revault-tests-', dir=d)
    print("Running tests in {}".format(directory))

    yield directory

    if os.listdir(directory) == []:
        shutil.rmtree(directory)


@pytest.fixture
def directory(request, test_base_dir, test_name):
    """Return a per-test specific directory.

    This makes a unique test-directory even if a test is rerun multiple times.

    """
    global __attempts
    # Auto set value if it isn't in the dict yet
    __attempts[test_name] = __attempts.get(test_name, 0) + 1
    directory = os.path.join(test_base_dir,
                             "{}_{}".format(test_name, __attempts[test_name]))
    request.node.has_errors = False

    yield directory

    # This uses the status set in conftest.pytest_runtest_makereport to
    # determine whether we succeeded or failed. Outcome can be None if the
    # failure occurs during the setup phase, hence the use to getattr instead
    # of accessing it directly.
    rep_call = getattr(request.node, 'rep_call', None)
    outcome = 'passed' if rep_call is None else rep_call.outcome
    failed = not outcome or request.node.has_errors or outcome != 'passed'

    # FIXME
    """
    if not failed:
        shutil.rmtree(directory)
    else:
        logging.debug("Test execution failed, leaving the test directory {}"
                      " intact.".format(directory))
    """


@pytest.fixture
def test_name(request):
    yield request.function.__name__


@pytest.fixture
def bitcoind(directory):
    bitcoind = BitcoinD(bitcoin_dir=directory)
    bitcoind.startup()

    yield bitcoind

    bitcoind.cleanup()


@pytest.fixture
def vault_factory(bitcoind):
    vault_factory = VaultFactory(bitcoind)

    yield vault_factory

    for vault in vault_factory.vaults:
        del vault
    bitcoind.cleanup()


@pytest.fixture
def sigserv(bitcoind):
    sigserver = SigServer(bitcoind.conf_file)
    with sigserver.test_client() as client:
        yield client
