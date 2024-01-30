function Update-Repo {
    git fetch

    git diff --quiet HEAD..origin
    $updatesAvailable = $LASTEXITCODE -ne 0

    if ($updatesAvailable) {
        Write-Host "Updates available from remote repository."

        git stash --include-untracked

        git pull

        git stash pop

        Write-Host "Repository updated and local changes reapplied."
    }
    else {
        Write-Host "No updates available from remote repository."
    }
}

Update-Repo

Read-Host -Prompt "Press Enter to exit"
