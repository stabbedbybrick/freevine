@echo off
setlocal

git fetch

git diff --quiet HEAD..origin
if errorlevel 1 (
    echo Updates available from remote repository.

    git stash --include-untracked

    git pull

    git stash pop

    echo Repository updated and local changes reapplied.
) else (
    echo No updates available from remote repository.
)

pause
