---
hide:
  - navigation
  - toc
---

<style>
.md-content__button { display: none; }
.hero {
  text-align: center;
  padding: 2rem 0 1rem;
}
.hero img { max-width: 320px; }
.hero h1 {
  font-size: 2.4rem;
  margin: 0.5rem 0 0.25rem;
  font-weight: 700;
}
.hero p.tagline {
  font-size: 1.15rem;
  color: var(--md-default-fg-color--light);
  margin-top: 0;
}
.hero .badges img { margin: 0 0.2rem; }
.cta {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  margin: 1.5rem 0 2rem;
  flex-wrap: wrap;
}
.cta a {
  display: inline-block;
  padding: 0.6rem 1.3rem;
  border-radius: 0.25rem;
  text-decoration: none;
  font-weight: 600;
}
.cta a.primary {
  background: var(--md-primary-fg-color);
  color: white;
}
.cta a.secondary {
  border: 2px solid var(--md-primary-fg-color);
  color: var(--md-primary-fg-color);
}
</style>

<div class="hero" markdown>

![psadmin.io](assets/io_blue_400.png){ width=320 }

# psa-cli

<p class="tagline">A unified command-line tool for PeopleSoft administration.</p>

<p class="badges">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: Beta">
  <img src="https://img.shields.io/badge/python-3.9+-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/PeopleTools-8.62-1E9CF0" alt="PeopleTools 8.62">
</p>

</div>

<div class="cta">
  <a class="primary" href="quickstart/">Quickstart →</a>
  <a class="secondary" href="install/">Install</a>
  <a class="secondary" href="https://github.com/psadmin-io/psa-cli">GitHub</a>
</div>

---

## What it does

`psa` streamlines PeopleSoft administration into a single, scriptable interface. It wraps `psadmin`, the DPK installer, and Puppet apply — keeping the parts that matter, smoothing the rough edges, and producing output that's pleasant to read in a terminal *and* parseable as JSON when you need it.

```bash
psa domain status APPDOM            # Check a domain
psa domain bounce APPDOM            # Stop, purge, flush, configure, start
psa dpk stage --version 8.62.04     # Stage a DPK
psa dpk apply --summary             # Run puppet apply, readable output
psa discover --json                 # Find local domains, emit JSON
```

## Highlights

- **Domain lifecycle** — `list`, `status`, `start`, `stop`, `restart`, `bounce`, `compare` with Rich output and `--json`.
- **DPK provisioning** — `stage → setup → init → sync → apply → cleanup`, with a 3-tier Hiera layout and custom module install.
- **`dpk apply --summary`** — filtered, readable Puppet output. Errors are surfaced with exit-code diagnostics.
- **Discovery** — find local PeopleSoft domains and optionally report them to an upstream API.
- **Resilient sudo** — file operations transparently escalate when the runtime user can't write.

## Status

!!! warning "Beta — not for production"
    psa-cli is pre-1.0. The CLI surface, config schema, and command behavior may change before 1.0. Tested against PeopleTools 8.62; older versions may work but are unverified. See [known limitations](https://github.com/psadmin-io/psa-cli/blob/main/CHANGELOG.md#known-limitations) for caveats around JSON output and the hidden `ops` / gated `kit` command groups.

## License

[MIT](https://github.com/psadmin-io/psa-cli/blob/main/LICENSE) © psadmin.io
