# Revault

This is a (WIP) demo implementation of Revault, a multiparty vault architecture relying on
pre-signed and revocable (revaultable) transactions.

This repo is a basic and insecure PoC.

- [About the architecture](#the-architecture)
- [About this demo](#the-demo)
- [Improvements](#improvements)
- [About us](#about-us)


### The architecture

The architecture is described [here](doc/revault.pdf), and the PoC is an instanciation of it (with 4
participants (N=4), 2 subset members (M=2) with one of N\M which can act as a spare
signer, and a CSV of 6 blocks).

### The demo

This PoC (/ demo / whatever insecure) is an implementation of such an architecture for 4
stakeholders (to simulate the needs of the first client, see below).

Currently a WIP, it serves to both:
- demonstrate the operation of a re-vault in practice with a big emphasis on being explicit and clear instead of secure (hence Python),
- to hopefully convince some people that it's worth financing the development of Revault
(but we need a nice GUI before this :/).

I tried to document as much as possible, beginning with the [transactions](doc/transactions.md).
Everything is in the [doc/](doc/) directory, which I'll try to fill with more information.

### Improvements

Of course, both the architecture and the demo are still in active development, and may
(read will) be perfected in the near future!

My focus is currently the feerate problem.

### About us

The architecture was first designed by [Kevin Loaec](https://twitter.com/KLoaec) from
[Chainsmiths](https://chainsmiths.com/) and has been worked (eventually somewhat implemented),
and improved by both of us (I'm [@darosior](https://github.com/darosior), or
[Antoine Poinsot](https://twitter.com/darosior) from [Leonod](https://leonod.com/)).

This architecture was at first commissioned by [NOIA](http://noia.capital), a trading fund with bitcoin
holdings. They were the first to sponsor this work, so big shoutout to them!

Credit is also due to Alekos Filini ([Github](https://github.com/afilini), [Twitter](https://twitter.com/afilini))
and, another person who prefers not to be named, for their feedback on an early
version of the architecture draft.


Finally, we are actively looking for either investors or potential users interested in
sponsoring the development of a usable and secure implementation of Revault, instead of
this toy!
If you might be interested, or just want to know more about Revault, feel free to drop me
a mail at darosior@protonmail.com / drop a mail to Kevin at kevin@chainsmiths.com
