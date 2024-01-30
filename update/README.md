## Requirements:

Freevine must be cloned with Git to use this feature.

```git clone https://github.com/stabbedbybrick/freevine.git freevine```

## Usage:

Inside Freevine folder, run `./update/update.ps1` (or .cmd/.sh)

## Information:

The script automates the update process through Git by 
fetching the main branch and checking for differences between local and remote repository. If updates are found, any local changes are "stashed" away while merging the new commits and then reapplied when finished.

> [!WARNING]
> These scripts are for basic usage. If you've made many local changes and commits, there's a bigger chance of merge conflicts and you might be better off doing the update manually where you have more control 
