# Third-party software

Generative Stage is MIT-licensed ([LICENSE](LICENSE); the scripts in `blender/` are covered by
[blender/LICENSE-NOTE.md](blender/LICENSE-NOTE.md)). It uses the packages below. This file is written by
`scripts/third_party.py` from `server/uv.lock`, `pipeline/requirements.txt` and `ui/package-lock.json`; do not edit it
by hand, run the script again after a lock changes. Python licences come from the metadata of the installed packages,
web licences from the lock file. It lists only what this repository ships or what `./install.sh` and the container
install; no model ships, and a model or program you add as an adapter carries its own licence. This is a list for
people, not legal advice.

Apart from the icon outlines listed under "Adapted", no third-party source code is copied or vendored into this repository.
The web app's favicon (`ui/public/favicon.ico`, two overlapping circles on a dark square) is original, made for this
project when the web app was renamed (it replaced the framework's default icon), and is under the repository's MIT
licence.

## Server (Python), run time

From `server/uv.lock`: what the server, the pipeline runner and the MCP server need.

| Package | Version | Licence |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| attrs | 26.1.0 | MIT |
| click | 8.5.1 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.16.0 | BSD-3-Clause |
| httpx2 | 2.16.0 | BSD-3-Clause |
| httpx2-jsfetch | 1.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 2.3.0 | MIT |
| mcp-types | 2.3.0 | MIT |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| pydantic | 2.14.3 | MIT |
| pydantic-core | 2.50.4 | MIT |
| pyjwt | 2.15.1 | MIT |
| python-multipart | 0.0.33 | Apache-2.0 |
| pywin32 | 312 | PSF (Python Software Foundation licence; also bundles notices for Scintilla, MAPI stubs and IDLE) |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| sse-starlette | 3.7.0 | BSD-3-Clause |
| starlette | 1.10.0 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.5 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

## Server (Python), development only

Tests, linting and type checking. Not needed to run the tool.

| Package | Version | Licence |
|---|---|---|
| ast-serialize | 0.13.1 | MIT |
| cffi | 2.1.1 | MIT-0 |
| colorama | 0.4.6 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| librt | 0.16.0 | MIT |
| mypy | 2.4.1 | MIT |
| mypy-extensions | 1.1.0 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pathspec | 1.1.1 | MPL-2.0 |
| pluggy | 1.7.0 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| pygments | 2.21.0 | BSD-2-Clause |
| pytest | 9.2.0 | MIT |
| ruff | 0.17.3 | MIT |
| types-jsonschema | 4.26.0.20261006 | Apache-2.0 |

## Tools environment (Python)

From `pipeline/requirements.txt`: the deterministic image and mesh stages.

| Package | Version | Licence |
|---|---|---|
| fast-simplification | 0.2.0 | MIT |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pillow | 13.0.0 | MIT-CMU |
| scipy | 1.18.1 | BSD-3-Clause (some bundled components carry other permissive licences) |
| trimesh | 5.2.0 | MIT |

## Web app (npm), in the built app and its tooling

From `ui/package-lock.json`: packages the built web app or the build itself needs. The built app bundles Angular, Angular Material, three.js, JSON Forms and markdown-it; the rest are build-time.

| Package | Version | Licence |
|---|---|---|
| @angular/animations | 22.2.5 | MIT |
| @angular/cdk | 22.2.6 | MIT |
| @angular/common | 22.2.5 | MIT |
| @angular/compiler | 22.2.5 | MIT |
| @angular/core | 22.2.5 | MIT |
| @angular/forms | 22.2.5 | MIT |
| @angular/material | 22.2.6 | MIT |
| @angular/platform-browser | 22.2.5 | MIT |
| @angular/router | 22.2.5 | MIT |
| @jsonforms/angular | 3.8.0 | MIT |
| @jsonforms/angular-material | 3.8.0 | MIT |
| @jsonforms/core | 3.8.0 | MIT |
| @standard-schema/spec | 1.1.0 | MIT |
| @types/json-schema | 7.0.15 | MIT |
| ajv | 8.20.0 | MIT |
| ajv-formats | 2.1.1 | MIT |
| argparse | 3.0.4 | PSF-2.0 |
| dayjs | 1.11.23 | MIT |
| entities | 8.1.0 | BSD-2-Clause |
| entities | 9.0.0 | BSD-2-Clause |
| fast-deep-equal | 3.1.3 | MIT |
| fast-uri | 3.1.9 | BSD-3-Clause |
| json-schema-traverse | 1.0.0 | MIT |
| linkify-it | 6.1.0 | MIT |
| lodash | 4.18.1 | MIT |
| markdown-it | 15.0.3 | MIT |
| mdurl | 2.1.0 | MIT |
| parse5 | 8.1.1 | MIT |
| punycode.js | 2.3.1 | MIT |
| require-from-string | 2.0.2 | MIT |
| rxjs | 7.8.2 | Apache-2.0 |
| three | 0.184.0 | MIT |
| tslib | 2.9.1 | 0BSD |
| uc.micro | 3.0.0 | MIT |
| zod | 4.6.6 | MIT |

## Web app (npm), development only

Test and build tools. Not part of the built app.

| Package | Version | Licence |
|---|---|---|
| @ampproject/remapping | 2.3.0 | Apache-2.0 |
| @angular-devkit/architect | 0.2202.6 | MIT |
| @angular-devkit/core | 22.2.6 | MIT |
| @angular-devkit/schematics | 22.2.6 | MIT |
| @angular/build | 22.2.6 | MIT |
| @angular/cli | 22.2.6 | MIT |
| @angular/compiler-cli | 22.2.5 | MIT |
| @asamuzakjp/css-color | 7.2.0 | MIT |
| @asamuzakjp/dom-selector | 10.0.5 | MIT |
| @babel/code-frame | 8.0.6 | MIT |
| @babel/compat-data | 8.0.5 | MIT |
| @babel/core | 8.0.1 | MIT |
| @babel/core | 8.0.5 | MIT |
| @babel/generator | 8.1.0 | MIT |
| @babel/helper-compilation-targets | 8.0.7 | MIT |
| @babel/helper-globals | 8.0.6 | MIT |
| @babel/helper-string-parser | 8.0.8 | MIT |
| @babel/helper-validator-identifier | 8.0.6 | MIT |
| @babel/helper-validator-option | 8.0.0 | MIT |
| @babel/helpers | 8.1.0 | MIT |
| @babel/parser | 8.1.0 | MIT |
| @babel/template | 8.0.0 | MIT |
| @babel/traverse | 8.1.0 | MIT |
| @babel/types | 8.1.0 | MIT |
| @bramus/specificity | 2.4.3 | MIT |
| @bufbuild/protobuf | 2.17.0 | (Apache-2.0 AND BSD-3-Clause) |
| @csstools/color-helpers | 6.1.2 | MIT-0 |
| @csstools/css-calc | 3.4.3 | MIT |
| @csstools/css-color-parser | 4.2.7 | MIT |
| @csstools/css-parser-algorithms | 4.0.2 | MIT |
| @csstools/css-syntax-patches-for-csstree | 1.1.16 | MIT-0 |
| @csstools/css-tokenizer | 4.0.2 | MIT |
| @dimforge/rapier3d-compat | 0.12.0 | Apache-2.0 |
| @emnapi/core | 1.11.3 | MIT |
| @emnapi/core | 2.0.0-alpha.6 | MIT |
| @emnapi/runtime | 1.11.3 | MIT |
| @emnapi/runtime | 2.0.0-alpha.6 | MIT |
| @emnapi/wasi-threads | 1.2.3 | MIT |
| @emnapi/wasi-threads | 2.2.0 | MIT |
| @esbuild/aix-ppc64 | 0.28.2 | MIT |
| @esbuild/android-arm | 0.28.2 | MIT |
| @esbuild/android-arm64 | 0.28.2 | MIT |
| @esbuild/android-x64 | 0.28.2 | MIT |
| @esbuild/darwin-arm64 | 0.28.2 | MIT |
| @esbuild/darwin-x64 | 0.28.2 | MIT |
| @esbuild/freebsd-arm64 | 0.28.2 | MIT |
| @esbuild/freebsd-x64 | 0.28.2 | MIT |
| @esbuild/linux-arm | 0.28.2 | MIT |
| @esbuild/linux-arm64 | 0.28.2 | MIT |
| @esbuild/linux-ia32 | 0.28.2 | MIT |
| @esbuild/linux-loong64 | 0.28.2 | MIT |
| @esbuild/linux-mips64el | 0.28.2 | MIT |
| @esbuild/linux-ppc64 | 0.28.2 | MIT |
| @esbuild/linux-riscv64 | 0.28.2 | MIT |
| @esbuild/linux-s390x | 0.28.2 | MIT |
| @esbuild/linux-x64 | 0.28.2 | MIT |
| @esbuild/netbsd-arm64 | 0.28.2 | MIT |
| @esbuild/netbsd-x64 | 0.28.2 | MIT |
| @esbuild/openbsd-arm64 | 0.28.2 | MIT |
| @esbuild/openbsd-x64 | 0.28.2 | MIT |
| @esbuild/openharmony-arm64 | 0.28.2 | MIT |
| @esbuild/sunos-x64 | 0.28.2 | MIT |
| @esbuild/win32-arm64 | 0.28.2 | MIT |
| @esbuild/win32-ia32 | 0.28.2 | MIT |
| @esbuild/win32-x64 | 0.28.2 | MIT |
| @exodus/bytes | 1.16.0 | MIT |
| @harperfast/extended-iterable | 1.0.5 | Apache-2.0 |
| @inquirer/ansi | 2.0.10 | MIT |
| @inquirer/checkbox | 5.2.8 | MIT |
| @inquirer/confirm | 6.3.2 | MIT |
| @inquirer/core | 12.0.6 | MIT |
| @inquirer/editor | 5.3.6 | MIT |
| @inquirer/expand | 5.1.8 | MIT |
| @inquirer/external-editor | 3.0.7 | MIT |
| @inquirer/figures | 2.0.10 | MIT |
| @inquirer/input | 5.1.9 | MIT |
| @inquirer/number | 4.2.6 | MIT |
| @inquirer/password | 5.2.5 | MIT |
| @inquirer/prompts | 8.7.2 | MIT |
| @inquirer/rawlist | 5.3.8 | MIT |
| @inquirer/search | 4.3.6 | MIT |
| @inquirer/select | 5.2.8 | MIT |
| @inquirer/type | 4.1.1 | MIT |
| @inquirer/type | 4.2.1 | MIT |
| @jridgewell/gen-mapping | 0.3.13 | MIT |
| @jridgewell/gen-mapping | 0.4.0-beta.0 | MIT |
| @jridgewell/resolve-uri | 3.1.2 | MIT |
| @jridgewell/sourcemap-codec | 1.6.0 | MIT |
| @jridgewell/trace-mapping | 0.3.31 | MIT |
| @listr2/prompt-adapter-inquirer | 4.2.7 | MIT |
| @lmdb/lmdb-darwin-arm64 | 3.5.6 | MIT |
| @lmdb/lmdb-darwin-x64 | 3.5.6 | MIT |
| @lmdb/lmdb-linux-arm | 3.5.6 | MIT |
| @lmdb/lmdb-linux-arm64 | 3.5.6 | MIT |
| @lmdb/lmdb-linux-x64 | 3.5.6 | MIT |
| @lmdb/lmdb-win32-arm64 | 3.5.6 | MIT |
| @lmdb/lmdb-win32-x64 | 3.5.6 | MIT |
| @modelcontextprotocol/core | 2.3.1 | Apache-2.0 |
| @modelcontextprotocol/server | 2.3.1 | Apache-2.0 |
| @msgpackr-extract/msgpackr-extract-darwin-arm64 | 3.0.7 | MIT |
| @msgpackr-extract/msgpackr-extract-darwin-x64 | 3.0.7 | MIT |
| @msgpackr-extract/msgpackr-extract-linux-arm | 3.0.7 | MIT |
| @msgpackr-extract/msgpackr-extract-linux-arm64 | 3.0.7 | MIT |
| @msgpackr-extract/msgpackr-extract-linux-x64 | 3.0.7 | MIT |
| @msgpackr-extract/msgpackr-extract-win32-x64 | 3.0.7 | MIT |
| @napi-rs/nice | 1.1.1 | MIT |
| @napi-rs/nice-android-arm-eabi | 1.1.1 | MIT |
| @napi-rs/nice-android-arm64 | 1.1.1 | MIT |
| @napi-rs/nice-darwin-arm64 | 1.1.1 | MIT |
| @napi-rs/nice-darwin-x64 | 1.1.1 | MIT |
| @napi-rs/nice-freebsd-x64 | 1.1.1 | MIT |
| @napi-rs/nice-linux-arm-gnueabihf | 1.1.1 | MIT |
| @napi-rs/nice-linux-arm64-gnu | 1.1.1 | MIT |
| @napi-rs/nice-linux-arm64-musl | 1.1.1 | MIT |
| @napi-rs/nice-linux-ppc64-gnu | 1.1.1 | MIT |
| @napi-rs/nice-linux-riscv64-gnu | 1.1.1 | MIT |
| @napi-rs/nice-linux-s390x-gnu | 1.1.1 | MIT |
| @napi-rs/nice-linux-x64-gnu | 1.1.1 | MIT |
| @napi-rs/nice-linux-x64-musl | 1.1.1 | MIT |
| @napi-rs/nice-openharmony-arm64 | 1.1.1 | MIT |
| @napi-rs/nice-win32-arm64-msvc | 1.1.1 | MIT |
| @napi-rs/nice-win32-ia32-msvc | 1.1.1 | MIT |
| @napi-rs/nice-win32-x64-msvc | 1.1.1 | MIT |
| @napi-rs/wasm-runtime | 1.2.7 | MIT |
| @oxc-parser/binding-android-arm-eabi | 0.156.0 | MIT |
| @oxc-parser/binding-android-arm64 | 0.156.0 | MIT |
| @oxc-parser/binding-darwin-arm64 | 0.156.0 | MIT |
| @oxc-parser/binding-darwin-x64 | 0.156.0 | MIT |
| @oxc-parser/binding-freebsd-x64 | 0.156.0 | MIT |
| @oxc-parser/binding-linux-arm-gnueabihf | 0.156.0 | MIT |
| @oxc-parser/binding-linux-arm-musleabihf | 0.156.0 | MIT |
| @oxc-parser/binding-linux-arm64-gnu | 0.156.0 | MIT |
| @oxc-parser/binding-linux-arm64-musl | 0.156.0 | MIT |
| @oxc-parser/binding-linux-ppc64-gnu | 0.156.0 | MIT |
| @oxc-parser/binding-linux-riscv64-gnu | 0.156.0 | MIT |
| @oxc-parser/binding-linux-riscv64-musl | 0.156.0 | MIT |
| @oxc-parser/binding-linux-s390x-gnu | 0.156.0 | MIT |
| @oxc-parser/binding-linux-x64-gnu | 0.156.0 | MIT |
| @oxc-parser/binding-linux-x64-musl | 0.156.0 | MIT |
| @oxc-parser/binding-openharmony-arm64 | 0.156.0 | MIT |
| @oxc-parser/binding-wasm32-wasi | 0.156.0 | MIT |
| @oxc-parser/binding-win32-arm64-msvc | 0.156.0 | MIT |
| @oxc-parser/binding-win32-ia32-msvc | 0.156.0 | MIT |
| @oxc-parser/binding-win32-x64-msvc | 0.156.0 | MIT |
| @oxc-project/types | 0.156.0 | MIT |
| @parcel/watcher | 2.6.0 | MIT |
| @parcel/watcher-android-arm64 | 2.6.0 | MIT |
| @parcel/watcher-darwin-arm64 | 2.6.0 | MIT |
| @parcel/watcher-darwin-x64 | 2.6.0 | MIT |
| @parcel/watcher-freebsd-x64 | 2.6.0 | MIT |
| @parcel/watcher-linux-arm-glibc | 2.6.0 | MIT |
| @parcel/watcher-linux-arm-musl | 2.6.0 | MIT |
| @parcel/watcher-linux-arm64-glibc | 2.6.0 | MIT |
| @parcel/watcher-linux-arm64-musl | 2.6.0 | MIT |
| @parcel/watcher-linux-x64-glibc | 2.6.0 | MIT |
| @parcel/watcher-linux-x64-musl | 2.6.0 | MIT |
| @parcel/watcher-win32-arm64 | 2.6.0 | MIT |
| @parcel/watcher-win32-x64 | 2.6.0 | MIT |
| @playwright/test | 1.65.0 | Apache-2.0 |
| @rolldown/binding-android-arm-eabi | 1.2.16 | MIT |
| @rolldown/binding-android-arm64 | 1.2.16 | MIT |
| @rolldown/binding-darwin-arm64 | 1.2.16 | MIT |
| @rolldown/binding-darwin-x64 | 1.2.16 | MIT |
| @rolldown/binding-freebsd-x64 | 1.2.16 | MIT |
| @rolldown/binding-linux-arm-gnueabihf | 1.2.16 | MIT |
| @rolldown/binding-linux-arm64-gnu | 1.2.16 | MIT |
| @rolldown/binding-linux-arm64-musl | 1.2.16 | MIT |
| @rolldown/binding-linux-ppc64-gnu | 1.2.16 | MIT |
| @rolldown/binding-linux-s390x-gnu | 1.2.16 | MIT |
| @rolldown/binding-linux-x64-gnu | 1.2.16 | MIT |
| @rolldown/binding-linux-x64-musl | 1.2.16 | MIT |
| @rolldown/binding-openharmony-arm64 | 1.2.16 | MIT |
| @rolldown/binding-win32-arm64-msvc | 1.2.16 | MIT |
| @rolldown/binding-win32-x64-msvc | 1.2.16 | MIT |
| @rolldown/pluginutils | 1.0.1 | MIT |
| @schematics/angular | 22.2.6 | MIT |
| @tweenjs/tween.js | 23.1.3 | MIT |
| @tybys/wasm-util | 0.10.4 | MIT |
| @types/chai | 5.2.3 | MIT |
| @types/deep-eql | 4.0.2 | MIT |
| @types/estree | 1.0.10 | MIT |
| @types/gensync | 1.0.5 | MIT |
| @types/jsesc | 2.5.1 | MIT |
| @types/stats.js | 0.17.4 | MIT |
| @types/three | 0.184.0 | MIT |
| @types/webxr | 0.5.24 | MIT |
| @vitejs/plugin-basic-ssl | 2.3.0 | MIT |
| @vitest/mocker | 5.1.0 | MIT |
| @vitest/spy | 5.1.0 | MIT |
| agent-base | 9.0.0 | MIT |
| ajv-formats | 3.0.1 | MIT |
| ansi-escapes | 7.3.0 | MIT |
| ansi-regex | 6.6.0 | MIT |
| ansi-styles | 6.2.3 | MIT |
| ansi-styles | 7.0.0 | MIT |
| assertion-error | 2.0.1 | MIT |
| baseline-browser-mapping | 2.11.35 | Apache-2.0 |
| beasties | 0.5.4 | Apache-2.0 |
| bidi-js | 1.1.0 | MIT |
| boolbase | 2.0.0 | ISC |
| browserslist | 4.29.5 | MIT |
| buffer-from | 1.1.2 | MIT |
| caniuse-lite | 1.0.30001823 | CC-BY-4.0 |
| chai | 6.3.0 | MIT |
| chalk | 5.6.2 | MIT |
| chardet | 2.2.0 | MIT |
| chokidar | 5.0.0 | MIT |
| cli-cursor | 5.0.0 | MIT |
| cli-spinners | 3.4.0 | MIT |
| cli-truncate | 6.2.0 | MIT |
| cli-width | 4.1.0 | ISC |
| cliui | 9.0.1 | ISC |
| colorjs.io | 0.7.1 | MIT |
| convert-source-map | 1.9.0 | MIT |
| convert-source-map | 2.0.0 | MIT |
| css-select | 7.0.0 | BSD-2-Clause |
| css-tree | 3.2.1 | MIT |
| css-what | 8.0.0 | BSD-2-Clause |
| data-urls | 8.0.0 | MIT |
| debug | 4.4.3 | MIT |
| decimal.js | 10.6.0 | MIT |
| detect-libc | 2.1.2 | Apache-2.0 |
| dom-serializer | 3.1.1 | MIT |
| domelementtype | 3.0.0 | BSD-2-Clause |
| domhandler | 6.0.1 | BSD-2-Clause |
| domutils | 4.0.2 | BSD-2-Clause |
| electron-to-chromium | 1.5.478 | ISC |
| emoji-regex | 10.6.0 | MIT |
| empathic | 2.1.0 | MIT |
| environment | 1.1.0 | MIT |
| es-module-lexer | 2.3.2 | MIT |
| esbuild | 0.28.2 | MIT |
| escalade | 3.2.0 | MIT |
| estree-walker | 3.0.3 | MIT |
| expect-type | 1.4.0 | Apache-2.0 |
| fast-string-truncated-width | 3.0.3 | MIT |
| fast-string-width | 3.0.2 | MIT |
| fast-wrap-ansi | 0.2.2 | MIT |
| fdir | 6.5.0 | MIT |
| fflate | 0.8.3 | MIT |
| flru | 1.0.2 | MIT |
| fsevents | 2.3.3 | MIT |
| gensync | 1.0.0-beta.2 | MIT |
| get-caller-file | 2.0.5 | ISC |
| get-east-asian-width | 1.7.0 | MIT |
| has-flag | 4.0.0 | MIT |
| hosted-git-info | 10.1.1 | ISC |
| html-encoding-sniffer | 7.0.0 | MIT |
| htmlparser2 | 12.0.0 | MIT |
| https-proxy-agent | 9.1.0 | MIT |
| iconv-lite | 0.7.3 | MIT |
| immutable | 5.1.9 | MIT |
| import-meta-resolve | 4.2.0 | MIT |
| is-extglob | 2.1.1 | MIT |
| is-fullwidth-code-point | 5.1.0 | MIT |
| is-glob | 4.0.3 | MIT |
| is-interactive | 2.0.0 | MIT |
| is-potential-custom-element-name | 1.0.1 | MIT |
| is-unicode-supported | 2.1.0 | MIT |
| js-tokens | 10.0.0 | MIT |
| jsdom | 30.1.3 | MIT |
| jsesc | 3.1.0 | MIT |
| json5 | 2.2.3 | MIT |
| jsonc-parser | 3.3.1 | MIT |
| lightningcss | 1.33.0 | MPL-2.0 |
| lightningcss-android-arm64 | 1.33.0 | MPL-2.0 |
| lightningcss-darwin-arm64 | 1.33.0 | MPL-2.0 |
| lightningcss-darwin-x64 | 1.33.0 | MPL-2.0 |
| lightningcss-freebsd-x64 | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm-gnueabihf | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm64-gnu | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm64-musl | 1.33.0 | MPL-2.0 |
| lightningcss-linux-x64-gnu | 1.33.0 | MPL-2.0 |
| lightningcss-linux-x64-musl | 1.33.0 | MPL-2.0 |
| lightningcss-win32-arm64-msvc | 1.33.0 | MPL-2.0 |
| lightningcss-win32-x64-msvc | 1.33.0 | MPL-2.0 |
| listr2 | 11.1.0 | MIT |
| lmdb | 3.5.6 | MIT |
| log-symbols | 7.0.1 | MIT |
| log-update | 8.0.0 | MIT |
| lru-cache | 11.5.3 | BlueOak-1.0.0 |
| magic-string | 1.4.1 | MIT |
| magic-string | 1.4.5 | MIT |
| mdn-data | 2.27.1 | CC0-1.0 |
| meshoptimizer | 1.1.1 | MIT |
| mimic-function | 5.0.1 | MIT |
| mrmime | 2.0.1 | MIT |
| ms | 2.1.3 | MIT |
| msgpackr | 1.12.1 | MIT |
| msgpackr-extract | 3.0.7 | MIT |
| mute-stream | 3.0.0 | ISC |
| nanoid | 3.3.20 | MIT |
| node-addon-api | 6.1.0 | MIT |
| node-addon-api | 7.1.1 | MIT |
| node-gyp-build-optional-packages | 5.2.2 | MIT |
| node-releases | 2.0.63 | MIT |
| npm-package-arg | 14.0.0 | ISC |
| nth-check | 3.0.1 | BSD-2-Clause |
| obug | 2.2.1 | MIT |
| obug | 3.0.0 | MIT |
| onetime | 7.0.0 | MIT |
| ora | 9.4.1 | MIT |
| ordered-binary | 1.6.3 | MIT |
| oxc-parser | 0.156.0 | MIT |
| parse5-html-rewriting-stream | 8.0.1 | MIT |
| parse5-sax-parser | 8.0.1 | MIT |
| picocolors | 1.1.1 | ISC |
| picomatch | 4.0.7 | MIT |
| piscina | 5.3.2 | MIT |
| playwright | 1.65.0 | Apache-2.0 |
| playwright-core | 1.65.0 | Apache-2.0 |
| postcss | 8.5.32 | MIT |
| postcss-media-query-parser | 0.2.3 | MIT |
| postcss-safe-parser | 7.1.0 | MIT |
| prettier | 3.9.10 | MIT |
| proc-log | 7.0.0 | ISC |
| proxy-agent-negotiate | 1.1.0 | MIT |
| punycode | 2.3.1 | MIT |
| readdirp | 5.1.1 | MIT |
| reflect-metadata | 0.2.2 | Apache-2.0 |
| restore-cursor | 5.1.0 | MIT |
| rolldown | 1.2.16 | MIT |
| safer-buffer | 2.1.2 | MIT |
| sass | 1.104.1 | MIT |
| sass-embedded | 1.104.1 | MIT |
| sass-embedded-all-unknown | 1.104.1 | MIT |
| sass-embedded-android-arm | 1.104.1 | MIT |
| sass-embedded-android-arm64 | 1.104.1 | MIT |
| sass-embedded-android-riscv64 | 1.104.1 | MIT |
| sass-embedded-android-x64 | 1.104.1 | MIT |
| sass-embedded-darwin-arm64 | 1.104.1 | MIT |
| sass-embedded-darwin-x64 | 1.104.1 | MIT |
| sass-embedded-linux-arm | 1.104.1 | MIT |
| sass-embedded-linux-arm64 | 1.104.1 | MIT |
| sass-embedded-linux-musl-arm | 1.104.1 | MIT |
| sass-embedded-linux-musl-arm64 | 1.104.1 | MIT |
| sass-embedded-linux-musl-riscv64 | 1.104.1 | MIT |
| sass-embedded-linux-musl-x64 | 1.104.1 | MIT |
| sass-embedded-linux-riscv64 | 1.104.1 | MIT |
| sass-embedded-linux-x64 | 1.104.1 | MIT |
| sass-embedded-unknown-all | 1.104.1 | MIT |
| sass-embedded-win32-arm64 | 1.104.1 | MIT |
| sass-embedded-win32-x64 | 1.104.1 | MIT |
| saxes | 6.0.0 | ISC |
| semver | 7.8.5 | ISC |
| signal-exit | 4.1.0 | ISC |
| slice-ansi | 10.0.1 | MIT |
| slice-ansi | 9.0.1 | MIT |
| source-map | 0.6.1 | BSD-3-Clause |
| source-map | 0.8.0 | BSD-3-Clause |
| source-map-js | 1.2.2 | BSD-3-Clause |
| source-map-support | 0.5.21 | MIT |
| std-env | 4.3.0 | MIT |
| stdin-discarder | 0.3.2 | MIT |
| string-width | 7.2.0 | MIT |
| string-width | 8.3.0 | MIT |
| strip-ansi | 7.2.0 | MIT |
| supports-color | 8.1.1 | MIT |
| sync-child-process | 1.1.1 | MIT |
| sync-message-port | 1.2.0 | MIT |
| tinybench | 6.2.3 | MIT |
| tinyexec | 1.3.1 | MIT |
| tinyglobby | 0.2.17 | MIT |
| tldts | 7.4.19 | MIT |
| tldts-core | 7.4.20 | MIT |
| tough-cookie | 6.1.0 | BSD-3-Clause |
| tr46 | 7.0.0 | MIT |
| typescript | 6.0.3 | Apache-2.0 |
| undici | 8.12.4 | MIT |
| update-browserslist-db | 1.3.4 | MIT |
| validate-npm-package-name | 8.0.0 | ISC |
| varint | 6.0.0 | MIT |
| verkit | 0.3.2 | MIT |
| verkit | 0.5.0 | MIT |
| vite | 8.3.5 | MIT |
| vite | 8.3.6 | MIT |
| vitest | 5.1.0 | MIT |
| w3c-xmlserializer | 6.0.0 | MIT |
| weak-lru-cache | 1.2.3 | MIT |
| webidl-conversions | 8.0.1 | BSD-2-Clause |
| whatwg-mimetype | 5.0.0 | MIT |
| whatwg-url | 17.3.0 | MIT |
| why-is-node-running | 3.2.1 | MIT |
| wrap-ansi | 10.0.2 | MIT |
| wrap-ansi | 9.0.2 | MIT |
| xml-name-validator | 5.0.0 | Apache-2.0 |
| xmlchars | 2.2.0 | MIT |
| xxhash-wasm | 1.1.0 | MIT |
| y18n | 5.0.8 | ISC |
| yargs | 18.1.0 | MIT |
| yargs-parser | 22.0.0 | ISC |
| yoctocolors | 2.2.0 | MIT |

## Adapted

What in this repository is adapted from elsewhere, and under which licence. They are treated as Apache-2.0 material; the licence text is at the link.

| What | From | Licence | Source |
|---|---|---|---|
| Five icon outlines (`landscape`, `person`, `category`, `key`, `place`) in `ui/src/app/world/kind-icon.ts`; four are copies or close redrawings, `key` may be original | Google's Material Icons | Apache-2.0 | https://github.com/google/material-design-icons |
