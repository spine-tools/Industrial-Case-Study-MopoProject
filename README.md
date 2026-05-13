# This repo is currently under construction

Once constructed, this repo should be an easy way to reproduce the Industrial Case workflow, both for collaboration during the project and for others to use in the future. It can also serve as an example for others that want to build additional data on top of the European Case.

# First Time Set Up Instructions

1. Install Python, Julia, and (optional) VSCode.
1. **Fork** this repository
1. **Clone** your fork
1. Go to the file `data/version_track.yml` and follow the link for each data source. Then be sure to download the version that matches the date in the version_track file.

    Folder structure in data/:
    - Biomass
    - Buildings
    - Cargo
    - Commodities
    - Electricity_Transmission
    - Energy_Conversion
    - Gas
    - geodata (currently in this repo, but should be moved to Zenodo)
    - Hydro
    - Industry
    - Rdemand
    - Transport
    - VRE

    !!! note: This does not seem like the ideal way to download the data. All the data should be in one location in the correct file structure, but right now that is under the Pan-European case (along with the .spinetoolbox etc) on Zenodo.

1. Choose one:
    - Open the project in **VSCode** and open a powershell terminal 
    - Open a regular **powershell or CMD terminal** and go to the project folder: `cd [path to folder]`

1. Create & activate a new **python environment**:
    ```
    py -3.13 -m venv .venv
    .venv\Scripts\Activate.ps1
    ```
    !Note: in CMD terminal:
    ```
    .venv\Scripts\activate.bat 
    ```
    
1. Install python dependencies: 

    `python -m pip install -r python-requirements.txt`

<!-- 1. Install julia dependencies:

    `julia --project=. -e "using Pkg; Pkg.instantiate()"` -->

1. Run spinetoolbox: `spinetoolbox`

1. Open the project: *File > Open Project > Industrial-Case-Study-MopoProject*

1. To make sure SpineToolbox is using the right Python environment for the project, **choose one:**
    - **If you're using SpineToolbox for ONLY this project** (and don't mind configuring globally for this project): 
    
        *File > Settings > Tools >* under *Python*, with Basic Console selected, click the folder button to browse and select the `python.exe` file in your .venv folder of this project. (Something like `C:/users/username/Industrial-Case-Study-MopoProject/.venv/Scripts/python.exe`)

    - **If you use SpineToolbox for other projects** (or don't want to configure globally):
    
        Double-click each Python tool (Red hammer) > for the *Interpreter* field, browse to find the Python of this project and select it, then click in the code-editor window and press CTRL+S to save before closing the tool window. (The path should be something like `C:/users/username/Industrial-Case-Study-MopoProject/.venv/Scripts/python.exe`. Once you find it, you can copy-paste to other tools.)

<!-- 1. Double-click on each Julia tool and set the Project to the project folder 

    (This makes sure it sees the correct julia environment and packages) -->

1. Double-click on each intermediate datastore (pink icons) > *New SpineDB > Okay* 
    
    (This will create sqlite files in the default folders SpineToolbox chooses.)

1. Set your project to "Consumer mode" so that moving blocks does not register as changing the workflow:

    *File > Project Settings > Consumer Mode*

  Note that when in Consumer Mode you are not able to modify the project.json file (links between tools, file names, etc.). Make sure you are in Author Mode when changing these so you won't lose your edits when you close the project.

You should be good to go!

# Updating the Workflow (collaborating)

Once you've completed the first-time setup, this is how you can start-up when returning to work on the project.

1. Open a terminal in the project folder, or open it VSCode.

1. Get any updates from others: 

    `git fetch origin --prune`

1. Merge the changes with your working directory: 

    `git merge --ff-only origin/main`

    (ff-only is a safety measure so it breaks if the changes conflict with your local changes)

Now you can open spinetoolbox and work on things. If you only work in the data and *running* the pipeline, just save and close. If you make changes to the pipeline that you want to share, follow these steps:

1. Check what you have changed:

    `git status`

1. If you want to see changes in a specific file:

     `git diff [FILE]`

1. **ADD** whichever changes you want to share:

     `git add [FILE]`

1. Check all the right files have been added:

    `git status`

1. OPTIONAL: Undo any changes you don't want to share:

    `git restore [FILE]`

1. **COMMIT** your changes: 

    `git commit -m "My message about what has changed"`

1. **PUSH** your changes to your own remote fork:

    `git push remote-name branch-name`

1. Click on the link, or go to your remote online to create a **PULL REQUEST** to the shared repo.

1. Someone else should review the Pull Request before merging it.

For more info on this workflow and how to fix merge errors, see the detailed version we wrote for Tulipa contributors [here.](https://tulipaenergy.github.io/TulipaEnergyModel.jl/stable/90-contributing/91-developer/#Contributing-Workflow)


# TODO Running the Workflow

- Launch spinetoolbox
- Tooling order
- Avoiding rerunning from raw
- Scenario filters
- Config files

# Note to developers

The data-pipelines section of this repository is a "subtree" of the ines/data-pipelines repository (on the EU_case branch).\
You can make any changes you like in those folders and it won't affect the original data-pipelines repo.\
And that repo can change completely and it won't impact this usage of it.\
If you WANT to push or pull changes from that repository, just ask an AI how to do that with a "git subtree."
