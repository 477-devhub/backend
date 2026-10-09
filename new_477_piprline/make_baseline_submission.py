"""Export previous real outputs into model-independent team submission CSV."""
from pathlib import Path
from pipeline477.team_benchmark import existing_results_submission, SUBMISSION_COLUMNS
from score import write_csv


def main():
    root = Path(__file__).resolve().parent
    rows = existing_results_submission(root / "results/full_pipeline_v2/results_readable.csv")
    destination = root / "submissions/preserved_baseline.csv"
    write_csv(destination, rows, SUBMISSION_COLUMNS)
    print({"submission": str(destination), "items": len(rows), "new_model_calls": 0})


if __name__ == "__main__":
    main()
