# Client package — 60 TPD melter SFC reduction

| File | What it is |
|---|---|
| `01_insights_path_to_target.ipynb` | **Start here.** What drives SFC in your furnace, where energy is lost today, what the recommenders deliver on your history, and the trial that takes us to the −2% target. All terms are explained at the top. |
| `02_model_training_and_recommender.ipynb` | How the gas and barrier-boost recommenders were trained, tested and chosen; the safety limits; and the **recommendation function** (enter plant values → setpoints) with a back-test against your history. |
| `report.py` | Chart helpers used by both notebooks (no calculations of its own). |

Both notebooks are saved **with their results and charts**, so they can be read without running anything.

**To re-run them** (Python 3.11, `pip install -r ../requirements.txt`), keep the project folder structure:
- `../src/data_prep.py`: data cleaning
- `../src/recommender.py`: the recommenders
- `../data/processed/`: cleaned data, built from your raw files

To get a recommendation, open notebook 02, edit `INPUTS` in section 9 and run the cell.
