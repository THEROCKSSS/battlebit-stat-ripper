# Contributing

1. Open an issue on GitHub with the problem and the expected behaviour.
2. Work on a feature branch and open a pull request; do not push to `main`.
3. Run the tests before opening a PR:

   ```powershell
   $env:PYTHONPATH = "src"
   python -m unittest discover -s tests -v
   ```

4. If you touch the decode schema, update `docs/FORMAT.md` and add a test with a
   synthetic payload. Never replace a decode failure with invented values.
5. If you touch the site, exercise the full register → upload → profile → private →
   404 flow.
6. Do not commit exported `.bbrstats` files, Steam IDs, `server/data/`, or secrets.

CI runs both suites on GitHub Actions (`.github/workflows/ci.yml`): the ripper on
Windows and the server on Linux. A PR is ready when both jobs are green.

The project is MIT licensed. By contributing you agree to license your changes under
the same terms.
