# This repo is currently under construction

Once constructed, this repo should be an easy way to reproduce the Industrial Case workflow, both for collaboration during the project and for others to use in the future. It can also serve as an example for others that want to build additional data on top of the European Case.

# First Time Set Up Instructions

1. Install Python, Julia, and (optional) VSCode.
2. **Fork** this repository
3. **Clone** your fork
4. Go to the file `data/version_track.yml` and follow the link for each data source. Then be sure to download the version that matches the date in the version_track file.

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

5. Choose one:
    - Open the project in **VSCode** and open a powershell terminal 
    - Open a regular **powershell or CMD terminal** and go to the project folder: `cd [path to folder]`

6. Create & activate a new **python environment**:
    ```
    py -3.13 -m venv .venv
    .venv\Scripts\Activate.ps1
    ```
    !Note: in CMD terminal:
    ```
    .venv\Scripts\activate.bat 
    ```
    
7. Install python dependencies: 

    `python -m pip install -r python-requirements.txt`

<!-- 1. Install julia dependencies:

    `julia --project=. -e "using Pkg; Pkg.instantiate()"` -->

8. Run spinetoolbox: `spinetoolbox`

9. Open the project: *File > Open Project > Industrial-Case-Study-MopoProject*

10. To make sure SpineToolbox is using the right Python environment for the project, **choose one:**
    - **If you're using SpineToolbox for ONLY this project** (and don't mind configuring globally for this project): 
    
        *File > Settings > Tools >* under *Python*, with Basic Console selected, click the folder button to browse and select the `python.exe` file in your .venv folder of this project. (Something like `C:/users/username/Industrial-Case-Study-MopoProject/.venv/Scripts/python.exe`)

    - **If you use SpineToolbox for other projects** (or don't want to configure globally):
    
        Double-click each Python tool (Red hammer) > for the *Interpreter* field, browse to find the Python of this project and select it, then click in the code-editor window and press CTRL+S to save before closing the tool window. (The path should be something like `C:/users/username/Industrial-Case-Study-MopoProject/.venv/Scripts/python.exe`. Once you find it, you can copy-paste to other tools.)

<!-- 11. Double-click on each Julia tool and set the Project to the project folder 

    (This makes sure it sees the correct julia environment and packages) -->

12. Double-click on each intermediate datastore (pink icons) > *New SpineDB > Okay* 
    
    (This will create sqlite files in the default folders SpineToolbox chooses.)

13. Set your project to "Consumer mode" so that moving blocks does not register as changing the workflow:

    *File > Project Settings > Consumer Mode*

  Note that when in Consumer Mode you are not able to modify the project.json file (links between tools, file names, etc.). Make sure you are in Author Mode when changing these so you won't lose your edits when you close the project.

You should be good to go!

# Updating the Workflow (collaborating)

Once you've completed the first-time setup, this is how you can start-up when returning to work on the project.

1. Open a terminal in the project folder, or open it VSCode.

2. Get any updates from your forked repo: 

    `git fetch origin --prune`

   or from others:

   'git fetch upstream --prune'

   *"origin" refers to your fork, "upstream" refers to the main repo

4. Merge the changes with your working directory: 

    `git merge --ff-only origin/main`

    (ff-only is a safety measure so it breaks if the changes conflict with your local changes)

Now you can open spinetoolbox and work on things. If you only work in the data and *running* the pipeline, just save and close. If you make changes to the pipeline that you want to share, follow these steps:

4. Check what you have changed:

    `git status`

5. If you want to see changes in a specific file:

     `git diff [FILE]`

6. **ADD** whichever changes you want to share:

     `git add [FILE]`

7. Check all the right files have been added:

    `git status`

8. OPTIONAL: Undo any changes you don't want to share:

    `git restore [FILE]`

9. **COMMIT** your changes: 

    `git commit -m "My message about what has changed"`

10. **PUSH** your changes to your own remote fork:

    `git push remote-name branch-name`

11. Click on the link, or go to your remote online to create a **PULL REQUEST** to the shared repo.

12. Someone else should review the Pull Request before merging it.

For more info on this workflow and how to fix merge errors, see the detailed version we wrote for Tulipa contributors [here.](https://tulipaenergy.github.io/TulipaEnergyModel.jl/stable/90-contributing/91-developer/#Contributing-Workflow)


# Running the Workflow

## Input data

Two datasets are needed besides this repository:

1. **Industrial case input data** (this case): https://doi.org/10.5281/zenodo.24565514.
   Unzip `IC1_mixedres_input_data.zip` in the repository root; it fills `data/`.
2. **Pan-European dataset** v0.6: https://doi.org/10.5281/zenodo.23496362.
   Unzip `Pan-European_Energy_System_Dataset.zip` into a folder `Pan-European_Energy_System_Dataset/`
   in the repository root (or elsewhere and set `eu_case_dir` in `data-pipelines/europe/userconfig.yaml`).
   It already contains the built sector databases; its importers do not need to be run. Only
   `.spinetoolbox/items/{heat_db,transport_db,industry_db,other_industry_db,hydro_db}` are used.

The country-level regions (DE, DK, NO, UK; all `countries` except BE/NL) are taken from the Pan-European dataset.

## Order

Run the Spine Toolbox items in this order:

1. All importers (`*_importer`, `gas_import`, `cargo_import`).
2. `power_fleet_pin` - fixes the NL+BE existing power fleet to `data-pipelines/europe/_power/power_fleet_pin.json`
   (`power_DB.py` draws retirement years at random).
3. `eu_country_rows` - copies the non-BE/NL country rows from the EU case into the sector databases.
4. `ines_builder`, then `template_1`, then `ines_to_spineopt`.
5. `merge_spineopt` - copies SpineOpt_target into Final_SpineOpt_Model (rerun it for a fresh model).
6. `clustering_input`, `make_cluster_seed`, `run_clustering`, `clustering_output`. The representative days are
   set by `representative_days` in `scenario_config.yml`.
7. `scenario_setup` - applies `scenario_config.yml`.
8. `Run_Model_Planning`.

Model settings are in `data-pipelines/europe/userconfig.yaml` (regions, CO2 data file) and
`Pan-European-Framework-Energy-System-Planning/src/_planning-input-processsing/scenario_config.yml` (scenario).

# Note to developers

The data-pipelines section of this repository is a "subtree" of the ines/data-pipelines repository (on the EU_case branch).\
You can make any changes you like in those folders and it won't affect the original data-pipelines repo.\
And that repo can change completely and it won't impact this usage of it.\
If you WANT to push or pull changes from that repository, just ask an AI how to do that with a "git subtree."
