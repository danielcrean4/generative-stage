# Generative Stage: web app

The Angular web app of Generative Stage. It talks to the server in `../server`
through `/api`: the world model and jobs on the main API (port 8780 by default) and the docs and
run views on the read-only API (port 8781 by default).

## Development server

```bash
npm ci
npm start
```

Then open `http://localhost:4200/`. The app reloads when a source file changes.

### Where the dev server sends API calls

`proxy.conf.cjs` reads the targets from `proxy-targets.cjs`. By default `/api/ro` goes to
`http://127.0.0.1:8781` and the rest of `/api` to `http://127.0.0.1:8780`. To use other servers,
use either of these (the environment wins over the file; each may set just one target):

- environment variables, set before `npm start`:

  ```bash
  GENSTAGE_API_TARGET=http://127.0.0.1:4311 GENSTAGE_READONLY_TARGET=http://127.0.0.1:4312 npm start
  ```

- a file `ui/proxy.local.json`, which git ignores:

  ```json
  { "api": "http://127.0.0.1:4311", "readonly": "http://127.0.0.1:4312" }
  ```

A target that is not a full `http://` or `https://` address, or a file with another key, stops
the dev server with a message naming the source.

## Tests and build

```bash
npx ng test --watch=false   # unit tests
npm run test:node           # dev proxy targets and the page title
npx ng build                # production build into dist/
```

The end-to-end tests (`npm run e2e:world`) start their own API and dev server on ports 4310 and
4311, so they do not touch servers that are already running.
