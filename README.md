# Tinyman Order Protocol

This repo contains the contracts that form the Tinyman Order Protocol system.

### Docs

User docs for Tinyman Orders can be found at [docs.tinyman.org](https://docs.tinyman.org).


### Contracts
The contracts are written in [Tealish](https://github.com/tinymanorg/tealish).
The specific version of Tealish is https://github.com/tinymanorg/tealish/tree/109a2f2e74549307fb002298f4189df3f0ed7c4f.

The annotated TEAL outputs and compiled bytecode are available in the build subfolders.


### Security
#### Reporting a Vulnerability
Reports of potential flaws must be responsibly disclosed to security@tinyman.org. Do not share details with anyone else until notified to do so by the team.


### Installing Dependencies
Note: Mac OS & Linux Only

```
% python3 -m venv ~/envs/tinyman-order-protocol
% source ~/envs/tinyman-order-protocol/bin/activate
(tinyman-order-protocol) % pip install -r requirements.txt
(tinyman-order-protocol) % python -m algojig.check
```

We recommend using VS Code with this Tealish extension when reviewing contracts written in Tealish: https://github.com/thencc/TealishVSCLangServer/blob/main/tealish-language-server-1.0.0.vsix


### Running Tests

```
# Run all tests (this can take a while)
(tinyman-order-protocol) % python -m unittest -v

```

Note: The tests read the `.tl` Tealish source files from the contracts directories, not the `.teal` build files.


### Compiling the Contract Sources

```
# Compile each set of contracts to generate the `.teal` files in the `build` subdirectories:
(tinyman-order-protocol) % tealish compile contracts/order
(tinyman-order-protocol) % tealish compile contracts/registry
```

### Licensing

The contents of this repository are licensed under the Business Source License 1.1 (BUSL-1.1), see [LICENSE](LICENSE).
