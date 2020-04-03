# Revault

This is a (WIP) demo implementation of Revault, a multiparty vault architecture relying on
pre-signed and revocable (revaultable) transactions.

This repo is a basic and insecure PoC.

- [About the architecture](#the-architecture)
- [About this demo](#the-demo)
- [Improvements](#improvements)
- [About us](#about-us)


### The architecture

Revault is a vault architecture designed for securing the storage **and usage** of
significant amount of bitcoins held my multiple parties (such as managers of an investment fund).

It aims at discouraging a theft as much as preventing it by going further than a
simple N-of-N multisig where:
- the stakeholders have full control over the multisig (a strong attack incentive as there is a high
chance to get full control over the coins)
- or they share this power with a trusted third party on which they rely for a non-trivial amount.

This architecture does not protect about intentional locking of funds (key erasure, for example, or
refusal to sign) and thus targets users who are able to resolve this kind of problems outside
the Bitcoin network (such as through the legal system).

Finally, it keeps some flexibility as it allows a subset of the stakeholders to emit day-to-day transactions without requiring all N holders to verify and sign.

The trick is to use N-of-N vaults for receiving funds and to pre-sign at reception a
so-called "emergency transaction" which sends funds to a "deep vault", i.e. a timelocked N-of-N
with N different keys [1].
At fund reception, 3 other transactions are also signed:
- The unvaulting transaction, which spends a vault output and spends to a relatively-timelocked
    M-of-N output OR to a N-of-N composed of the keys used for the initial vault.
- The cancel transaction, which spends an unvaulting transaction and sends back the
    coins to a "normal" vault.
- The emergency transaction, which spends the unvaulting transaction to the emergency deep
    vault.
Of course, transactions are signed backward (à la payment channels).

A stakeholder can revoke a spend to an (unknown / untrusted address) during the CSV delay.

More details are available in the [architecture document](doc/archi.pdf).

[1] These N keys are preferably held by each stakeholder in some place which are both hard
to access and geographically distant.


### The demo

This PoC (/ demo / whatever insecure) is an implementation of such an architecture for 4
stakeholders (to simulate the needs of the first client, see below).

Currently a WIP, it serves to both:
- demonstrate the operation of a re-vault in practice with a big emphasis on being explicit and clear instead of secure (hence Python),
- to hopefully convince some people that it's worth financing the development of Revault
(but we need a nice GUI before this :/).

I tried to document as much as possible, begining with the [transactions](doc/transactions.md).
Everything is in the [doc/](doc/) directory, which I'll try to fill with more informations.

### Improvements

Of course, both the architecture and the demo are still in active development, and may
(read will) be perfected in the near future!

My focus is currently the feerate problem.

### About us

The architecture was first designed by [Kevin Loaec](https://twitter.com/KLoaec) from
[Chainsmiths](https://chainsmiths.com/) and has been worked (eventually somewhat implemented),
and improved by both of us (I'm [@darosior](https://github.com/darosior), or
[Antoine Poinsot](twitter.com/darosior) from [Leonod](https://leonod.com/)).

This architecture was at first comissioned by [NOIA](), a trading fund with bitcoin
holdings. They were the first to sponsor this work, so big shoutout to them !

Credit is also due to Alekos Filini ([Github](https://github.com/afilini), [Twitter](https://twitter.com/afilini))
and another person who prefered we not mention their name, for their feedback on early
version of the architecture draft.


Finally, we are actively looking for either investors or potential users interested in
sponsoring the development of an usable and secure implementation of Revault, instead of
this toy !
If you might be interested, or just want to know more about Revault, feel free to drop me
a mail at darosior@protonmail.com / drop a mail to Kevin at kevin@chainsmiths.com
