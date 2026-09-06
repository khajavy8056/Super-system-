@echo off
REM One-shot: activate the GitHub Actions workflows (needs a GitHub login with `workflow` scope).
cd /d "%~dp0\.."
if not exist ".github\workflows" mkdir ".github\workflows"
git mv -f installer\ci\release-windows.yml .github\workflows\release-windows.yml
git mv -f installer\ci\release-android.yml .github\workflows\release-android.yml 2>nul
git commit -m "ci: activate release workflows (Windows installer + Android APK)"
git push
echo Done. Push a v* tag or run the workflow from the Actions tab.
pause
