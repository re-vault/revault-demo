import bitcoin

from bitcoin.core import b2x
from bitcoin.core.script import CScript, OP_4, OP_CHECKMULTISIG
from bitcoin.wallet import CBitcoinAddress
from decimal import Decimal, getcontext
from fixtures import bitcoind, directory, test_base_dir, test_name
from vaultaic.transactions import (
    vault_txout, vault_script,
)


bitcoin.SelectParams("regtest")
getcontext().prec = 8


def test_vault_txout(bitcoind):
    """Test that vault_txout() produces a valid output."""
    amount = Decimal("50") - Decimal("250") * Decimal(10**-8)
    addresses = [bitcoind.rpc.getnewaddress() for i in range(4)]
    pubkeys = [bytes.fromhex(bitcoind.rpc.getaddressinfo(addr)["pubkey"])
               for addr in addresses]
    privkeys = [bitcoind.rpc.dumpprivkey(addr) for addr in addresses]
    txo = vault_txout(pubkeys, amount)
    addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount)
    new_amount = amount - Decimal("500") * Decimal(10**-8)
    # Just pay to the same script, we don't care
    tx = bitcoind.rpc.createrawtransaction([{"txid": txid, "vout": 0}],
                                           [{addr: float(new_amount)}])
    tx = bitcoind.rpc.signrawtransactionwithkey(tx, privkeys, [
        {
            "txid": txid,
            "vout": 0,  # no change output
            "scriptPubKey": b2x(txo.scriptPubKey),
            "witnessScript": b2x(vault_script(pubkeys)),
            "amount": str(amount)
         }
    ])
    bitcoind.send_tx(tx["hex"])
