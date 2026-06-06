# Veloura Public Release Checklist

Use this checklist before publishing Veloura as a public/global Python package.

## Identity

- Confirm the public package name on PyPI: `veloura-audio`
- Choose the legal license and add a `LICENSE` file
- Decide the copyright owner or contributor line
- Add official project URLs to `pyproject.toml`:
  - Homepage
  - Source repository
  - Issue tracker
  - Documentation

## Package Metadata

- Keep `veloura.__version__` and `pyproject.toml` version in sync
- Confirm the Python version floor: currently `>=3.12`
- Confirm optional extras:
  - `stream` for `yt-dlp`
  - `discord` for Discord voice support
  - `all` for every optional integration
- Recheck classifiers after choosing a license

## Local Verification

```bash
python3 -m unittest discover -s tests
python3 -m py_compile veloura/*.py veloura/audio/*.py examples/*.py
python3 -m build
python3 -m twine check dist/*
```

## Publishing Flow

1. Build from a clean source tree.
2. Upload to TestPyPI first.
3. Install from TestPyPI in a fresh virtual environment.
4. Run `python -m veloura presets`.
5. Test `prepare`, `analyze`, and the streamer example with local files.
6. Test stream resolution with `pip install "veloura-audio[stream]"`.
7. Publish the same checked artifacts to PyPI.

## Release Notes

For each public release, include:

- New features
- Compatibility notes
- Dependency or Python-version changes
- Known limitations
- Migration notes for renamed or deprecated public APIs
