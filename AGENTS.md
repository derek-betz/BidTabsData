# BidTabsData Agent Notes

Use this workflow when publishing a new BidTabsData release.

Release checklist:
1. Ensure `data/` is updated and committed.
2. Create the release zip:
   - `py tools/create_release_zip.py --version vYYYY-MM-DD`
3. Archive the zip locally:
   - Move `BidTabsData-vYYYY-MM-DD.zip` into `artifacts/` (this folder is gitignored).
4. Tag and push:
   - `git tag vYYYY-MM-DD`
   - `git push`
   - `git push origin vYYYY-MM-DD`
5. Publish the GitHub release:
   - `gh release create vYYYY-MM-DD artifacts/BidTabsData-vYYYY-MM-DD.zip --title "BidTabsData vYYYY-MM-DD" --notes "<notes>"`
   - Include a short contents summary (file count + date range) in the notes.
