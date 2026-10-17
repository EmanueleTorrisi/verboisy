<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Publishing and customer delivery

**Publish to PyPI; install with pip or pipx.** PyPI packages are public. It has no
customer access-code mechanism for private downloads. PyPI API tokens authorize
uploads; they are not customer keys. Never give an upload token to a buyer.
See [PyPI help](https://pypi.org/help/#how-can-i-publish-my-private-packages-to-pypi).

## Choose delivery

| Channel | Download access | Entitlement | Suitable use |
| --- | --- | --- | --- |
| Public PyPI | Everyone | Separate written commercial agreement | Public source-inspection distribution or a deliberately public edition |
| Private wheel | Approved recipients | Agreement, payment and protected delivery | Initial customers and evaluations |
| Private index | Authenticated customer accounts | Per-customer read access and update entitlement | Repeat installations and controlled updates |
| Hosted service | Service accounts | Server-enforced account/subscription controls | Future offering; not implemented here |

Start with private wheels for selected customers, then consider a managed private
index for repeat installs. A wheel contains recoverable code. Private delivery
controls downloading, not copying afterward; revocation does not disable installed copies.

## Prepare tested artifacts

```bash
source .venv/bin/activate
python scripts/verify_release.py --native --audit --package
read -r -p "Passing engineering report path printed above: " VERBOISY_REPORT
python scripts/package_release.py prepare --report "$VERBOISY_REPORT"
python scripts/package_release.py show
```

The selector requires a passing report, current source and exact tested wheel/sdist
hashes. No broad `dist/*` upload is used. The candidate file remains ignored in `build/`.

## Public upload from the terminal

One-time registration, email verification, 2FA and token setup require the account
interface: [PyPI](https://pypi.org/account/register/) and
[TestPyPI](https://test.pypi.org/account/register/) have separate accounts and tokens.
There is no supported terminal-only replacement for that registration. No editor
is needed; package preparation and upload below are terminal commands.

For a new project, use a pending Trusted Publisher or an account-scoped upload token;
after it exists, prefer project-scoped tokens. Confirm your account controls the
project name. A pending publisher does not reserve it. Do not put tokens in commands,
committed files or customer deliveries.

First test the upload. **TestPyPI is public too**:

```bash
python scripts/package_release.py upload --target testpypi
```

Type `PUBLIC testpypi` when prompted. Twine uses `__token__` and prompts privately
for the complete TestPyPI token. Download only this package from TestPyPI, then
install the wheel and obtain dependencies from normal PyPI:

```bash
VERBOISY_TEST_DIR="$(mktemp -d "$PWD/build/testpypi-XXXXXX")"
VERBOISY_VERSION="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
python -m pip download --no-deps --only-binary=:all: \
  --index-url https://test.pypi.org/simple/ \
  --dest "$VERBOISY_TEST_DIR" "verboisy==$VERBOISY_VERSION"
python -m venv "$VERBOISY_TEST_DIR/environment"
"$VERBOISY_TEST_DIR/environment/bin/python" -m pip install \
  --index-url https://pypi.org/simple/ "$VERBOISY_TEST_DIR"/*.whl
"$VERBOISY_TEST_DIR/environment/bin/python" -m pip check
"$VERBOISY_TEST_DIR/environment/bin/verboisy" --help
```

After reviewing public source-inspection distribution and its claims:

```bash
python scripts/package_release.py upload --target pypi
```

Type `PUBLIC pypi` and enter the PyPI token when prompted. This path does not claim
full product qualification. To require all seven reviews for a production release:

```bash
python scripts/release_matrix.py require-complete
python scripts/package_release.py upload --target pypi --production
```

Choose one PyPI upload path, not both. Uploaded filenames cannot be overwritten or
reused after deletion. New versions must update `pyproject.toml` and
`src/verboisy/__init__.py` consistently, with separate commits, fresh verification
and renewed reviews. The retained `1.0.0` metadata does not assert readiness.

After publication, authorized customers can install:

```bash
pipx install verboisy
verboisy --help
# Or, for Python imports:
python3 -m venv .venv
source .venv/bin/activate
python -m pip install verboisy
```

## Optional GitHub Trusted Publishing

The existing `publish.yml` workflow uses CI-verified artifacts and OIDC. It requires
a public repository and `RELEASE_ENABLED=true`, and checks the tag against the version.
It does not enforce the seven human gates: the release owner must do so before any
production publication. Keep it disabled for private delivery or manual publication.

For this alternative to manually uploading the same version, configure a PyPI
Trusted Publisher for owner `EmanueleTorrisi`, repository `verboisy`, workflow
`publish.yml`, environment `pypi`. Configure the GitHub environment and appropriate
required reviewers. These are one-time account settings. With GitHub CLI installed
and authenticated, an existing public remote, and a reviewed clean commit:

```bash
python scripts/release_matrix.py require-complete
git status --short
git push origin main
gh variable set RELEASE_ENABLED --body true --repo EmanueleTorrisi/verboisy
VERBOISY_VERSION="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
git tag -a "v$VERBOISY_VERSION" -m "Release Verboisy $VERBOISY_VERSION"
git push origin "v$VERBOISY_VERSION"
gh release create "v$VERBOISY_VERSION" --verify-tag \
  --title "Verboisy $VERBOISY_VERSION" --notes-file CHANGELOG.md
```

Publishing that GitHub release triggers the public PyPI workflow. Do not run this
for a version already uploaded manually. See [Trusted Publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [new-project setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Private sales and delivery

A standard initial process is: agree scope and price, obtain the written license,
collect payment or satisfy agreed purchase terms, deliver privately, confirm
installation, retain an order/version/entitlement record. Email may carry a protected
customer-specific download link and installation notes. This kit does not send email,
take payment, create an agreement or provision customer accounts.

Use the actual agreed customer license PDF:

```bash
read -r -p "Order reference (letters, digits, - or _): " VERBOISY_ORDER
read -r -p "Absolute path to the agreed customer PDF: " VERBOISY_AGREEMENT
python scripts/customer_bundle.py \
  --order "$VERBOISY_ORDER" --agreement "$VERBOISY_AGREEMENT"
```

The ignored ZIP contains the tested wheel, agreement, license, notices, installation
instructions and SHA-256 checksums. It refuses to overwrite an existing order ZIP.
The order reference tracks delivery; it is not a secret or activation key. The helper
checks a PDF header, not signatures or legal sufficiency. Only include the agreement
intended for that recipient. Keep customer documents and ZIPs out of Git.

Deliver through authenticated storage or a portal with scoped, expiring access.
Installing the wheel does not contact a Verboisy activation server. Dependencies
still download from a package index; the bundle is not a fully offline installation.

## Private index and customer codes

Use a registry with per-customer read credentials, revocation, audit logs, TLS and
a controlled PyPI proxy/mirror for dependencies. Reserve private project names so
public packages cannot shadow them. Separate publishing credentials from customer
read credentials. A token generated by that registry is the customer's download code.

For a registry supporting basic authentication and an OS keyring, substitute its
host and customer username at the prompts:

```bash
python -m pip install keyring --index-url https://pypi.org/simple/
read -r -p "Private registry hostname: " VERBOISY_REGISTRY
read -r -p "Customer read-only username: " VERBOISY_CUSTOMER
python -m keyring set "$VERBOISY_REGISTRY" "$VERBOISY_CUSTOMER"
python -m pip install --keyring-provider import \
  --index-url "https://$VERBOISY_CUSTOMER@$VERBOISY_REGISTRY/simple/" verboisy
```

The keyring prompts for the read token; it stays out of the URL and command history.
Use the registry's authentication plugin where required. Usernames must be URL-safe
or encoded according to pip's guidance. For pipx, configure an installed keyring CLI
and pip's `subprocess` provider using the registry's documented setup.

Do not use `--extra-index-url` for private packages: pip documents a dependency
confusion risk. Use one controlled index or install the exact delivered wheel.
Signed activation keys, expiry checks, seats and offline grace periods require a
separate implemented licensing system. A code in PyPI metadata does not provide one.

## Commercial terms

Agree customer identity, users and deployments, integration/redistribution rights,
fees, term, update entitlement, support, response commitments, data responsibilities
and termination. Obtain qualified review of the actual agreement and prior BSD
grants. This guide creates no customer contract and revokes no historical rights.
Sell only available capabilities and services actually included in the agreement;
[commercial product directions](commercial.md) remain distinct from shipped features.

## Official references

- [PyPI accounts, tokens, private packages and filenames](https://pypi.org/help/)
- [PyPA packaging and uploading](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [PyPA private package indexes](https://packaging.python.org/en/latest/guides/hosting-your-own-index/)
- [pip authentication and keyring](https://pip.pypa.io/en/stable/topics/authentication/)
- [pip index selection and dependency confusion](https://pip.pypa.io/en/stable/cli/pip_install/)
- [PyPA README rendering](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/)
