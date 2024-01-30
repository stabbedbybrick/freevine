#!/bin/bash

function update_repo {

    git fetch

    if git diff --quiet HEAD..origin; then
        echo "No updates available from remote repository."
    else
        echo "Updates available from remote repository."

        git stash --include-untracked

        git pull

        git stash pop

        echo "Repository updated and local changes reapplied."
    fi
}

update_repo

read -p "Press Enter to exit"
