# Client package — 60 TPD melter SFC reduction

| File | What it is |
|---|---|
| `01_insights_path_to_target.ipynb` | **Start here.** What drives SFC in your furnace, where energy is lost today, what the recommenders deliver on your history, and the trial that takes us to the −2% target. All terms are explained at the top. |
| `02_model_training_and_recommender.ipynb` | How the gas and barrier-boost recommenders were trained, tested and chosen; the safety limits; and the **recommendation function** (enter plant values → setpoints) with a back-test against your history. |
| `03_eda_features_insights.ipynb` | **Client demo walkthrough.** Key terms and a sketch of the melter, then: Part 1 EDA (data received and cleaned, typical day, distributions, 13 months at a glance, one day in 15-min detail, **correlation heat map**, what goes with extra energy once draw is removed); Part 2 features (what was built, the draw-adjusted yardstick, feature effects and tests); Part 3 twelve insights; Part 4 how the findings lower SFC (finding → action, a worked recommendation, history replay, path to 2%, trial). Charts come from `eda_insights.py`. |
| `eda_insights.py` | Charts and tables for notebook 03 (builds on `report.py`). |
| `SFC_Optimisation_Client_Presentation.pptx` | 40-slide client presentation: problem and acceptance criteria, SFC formula, 10 EDA relationships, heat map, golden batch, best/worst days, input data and split method, models compared, final model, evaluation, Databricks packaging, operator setpoints with historical ranges, path to −2%, trial plan. Speaker notes on every slide. |
| `report.py` | Chart helpers used by both notebooks (no calculations of its own). |

Both notebooks are saved **with their results and charts**, so they can be read without running anything.

**To re-run them** (Python 3.11, `pip install -r ../requirements.txt`), keep the project folder structure:
- `../src/data_prep.py`: data cleaning
- `../src/recommender.py`: the recommenders
- `../data/processed/`: cleaned data, built from your raw files

To get a recommendation, open notebook 02, edit `INPUTS` in section 9 and run the cell.
