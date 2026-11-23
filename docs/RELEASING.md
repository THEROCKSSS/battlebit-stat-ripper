# Releasing

Releases are built by GitHub Actions from a tag; nothing is uploaded by hand.

1. Make sure `main` is green in CI and the version in `pyproject.toml` matches the
   tag you are about to cut.
2. Update `HANDOFF.md` and the changelog section of the release notes if the release
   changes behaviour.
3. Push the tag:

   ```powershell
   git tag -a v0.3.0 -m "v0.3.0"
   git push origin v0.3.0
   ```

4. `.github/workflows/release.yml` runs `build\build.ps1` on `windows-latest` and
   creates the GitHub release with:
   - `BattleBitStatRipper.exe`
   - `bbr-ripper-cli.exe`
   - `BattleBitStatRipper-windows-x64.zip`
5. Verify the release page shows all three assets and download one to check it is
   not truncated. The site's download page can then point at the release.

To rebuild without a release, run the workflow manually from the Actions tab; it
attaches assets to the tag that triggered it, so use a draft tag or run
`build\build.ps1` locally instead.

The executables are unsigned. SmartScreen will warn on first run; that is expected
until a code-signing certificate is set up.
