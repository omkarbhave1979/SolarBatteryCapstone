"""Show a 24-hour persistence-based battery schedule for an Ausgrid sample home."""
from datetime import date
import json

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import numpy as np

from battery_dispatch import BatteryDispatch
from schedule_day import ROOT, schedule


def schedule_figure(delivery, household, starting_kwh, meter_csv, method="weekly_persistence", *, demo_profile_date=None):
    rows = list(schedule(
        meter_csv, household, delivery, starting_kwh, method, demo_profile_date=demo_profile_date
    ))
    _, solar, load, _, power, stored = map(np.asarray, zip(*rows))
    stored = np.r_[starting_kwh, stored]
    charge_kw = power.clip(min=0)
    discharge_kw = (-power).clip(min=0)

    scenario = json.loads((ROOT / "config/scenario.json").read_text())
    battery = BatteryDispatch(scenario)
    _, peak = battery.rates(delivery)
    target = battery.states[battery.initial]
    edges = np.arange(49) / 2
    slots = edges[:-1]
    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 10), layout="constrained")
    fig.suptitle("Recommended battery schedule for the next 24 hours", weight="bold", fontsize=16)
    label = method.replace("_", " ")
    if demo_profile_date is not None:
        fig.suptitle("Illustrative 24-hour battery schedule", weight="bold", fontsize=16)
        label = "historical meter profile · demonstration only"
    else:
        label = f"{label} forecast"
    axes[0].set_title(f"Household {household} · {delivery:%A, %d %B %Y} · {label}", fontsize=11)
    axes[0].stairs(solar * 2, edges, label="Forecast solar", color="#ad6508", linewidth=2)
    axes[0].stairs(load * 2, edges, label="Forecast household demand", color="#24557c", linewidth=2)
    axes[0].set_ylabel("Average power (kW)")
    axes[0].legend(loc="upper left")

    axes[1].bar(slots, charge_kw, width=0.48, align="edge", color="#137d71", label="Charge battery")
    axes[1].bar(slots, -discharge_kw, width=0.48, align="edge", color="#7251a2", label="Draw from battery")
    axes[1].axhline(0, color="#344052", linewidth=0.8)
    axes[1].set_ylabel("Battery power (kW)")
    axes[1].legend(loc="upper left", ncols=2)

    grid_import = np.maximum(2 * (load - solar) + power, 0)
    axes[2].bar(slots, grid_import, width=0.48, align="edge", color="#b96b24", label="Draw from grid")
    axes[2].bar(slots, discharge_kw, width=0.48, align="edge", bottom=grid_import,
                color="#7251a2", label="Draw from battery")
    axes[2].set_ylabel("Power supplied (kW)")
    axes[2].legend(loc="upper left", ncols=2)

    axes[3].plot(edges, stored, linewidth=2.2, color="#24557c", label="Planned stored energy")
    axes[3].axhline(target, linestyle="--", color="#697586", label=f"{target:g} kWh target")
    axes[3].set(ylabel="Stored energy (kWh)", xlabel="Sydney local time", ylim=(0, scenario["battery"]["capacity_kwh"]))
    axes[3].legend(loc="upper left", ncols=2)
    peak_slots = np.flatnonzero(peak)
    if peak_slots.size:
        left, right = edges[peak_slots[0]], edges[peak_slots[-1] + 1]
        for axis in axes:
            axis.axvspan(left, right, color="#f5c163", alpha=0.24, zorder=-1)
        axes[3].text((left + right) / 2, 0.55, "Peak tariff", ha="center", fontsize=9)
    for axis in axes:
        axis.grid(axis="y", alpha=0.22)
        axis.set_xlim(0, 24)
    axes[3].xaxis.set_major_locator(MultipleLocator(3))
    axes[3].xaxis.set_major_formatter(lambda hour, _: f"{hour:02.0f}:00")
    return fig


if __name__ == "__main__":
    sample = ROOT / "data/sample/ausgrid_sample.csv"
    figure = schedule_figure(date(2012, 7, 23), "1", 5, sample)
    figure.suptitle("Historical example · 24-hour battery schedule", weight="bold", fontsize=16)
    figure.savefig(ROOT / "results/next_day_schedule.png", dpi=160)
