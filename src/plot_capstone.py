"""Plot held-out forecast errors and inventory-adjusted dispatch costs."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

LABELS = {
    "weekly_persistence": "Weekly persistence",
    "ridge": "Ridge regression",
    "linear_regression": "Linear regression",
    "gradient_boosting": "Gradient boosting",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("figure", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    test = report["test"]
    methods = list(test["forecast"])
    positions = np.arange(len(methods))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), layout="constrained")
    for offset, target in ((-0.18, "solar"), (0.18, "load")):
        values = [test["forecast"][method]["all"][target]["rmse"] for method in methods]
        axes[0].bar(positions + offset, values, width=0.34, label=target.capitalize())
    axes[0].set_xticks(positions, [LABELS[method] for method in methods], rotation=12)
    axes[0].set_ylabel("RMSE (kWh per half-hour)")
    axes[0].set_title("Day-ahead forecast error")
    axes[0].legend()

    dispatch = test["dispatch"]
    selected = report["selected_ml_model"]
    costs = [
        dispatch["no_battery_cost_aud"],
        dispatch["weekly_persistence"]["inventory_adjusted_cost_aud"],
        dispatch[selected]["inventory_adjusted_cost_aud"],
    ]
    bars = axes[1].bar(
        ["No battery", "Persistence\nschedule", f"{LABELS[selected]}\nschedule"],
        np.asarray(costs) / dispatch["household_days"],
        color=["#8995a0", "#326785", "#167862"],
    )
    axes[1].bar_label(bars, fmt="$%.2f", padding=3)
    axes[1].set_ylim(0, max(bar.get_height() for bar in bars) * 1.15)
    axes[1].set_ylabel("AUD per scored household-day")
    axes[1].set_title("Net electricity cost under the illustrative tariff")
    fig.suptitle("Ausgrid held-out evaluation")
    fig.savefig(args.figure, dpi=160)


if __name__ == "__main__":
    main()
