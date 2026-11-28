"""Day-ahead dispatch and causal meter replay on a discrete charge grid."""
from datetime import time
from functools import cache

import numpy as np


class BatteryDispatch:
    def __init__(self, scenario, step_kwh=0.5):
        battery = scenario["battery"]
        tariff = scenario["tariff"]
        minimum = battery["minimum_soc_kwh"]
        maximum = battery["maximum_soc_kwh"]
        initial = battery["initial_soc_kwh"]
        hours = scenario["interval_minutes"] / 60
        if (
            not 0 <= minimum <= initial <= maximum <= battery["capacity_kwh"]
            or not battery["grid_charging"]
            or battery["battery_export"]
            or battery["terminal_soc_policy"] != "target_configured_initial_with_penalty"
            or scenario["interval_minutes"] != 30
            or tariff["clock"] != "Australia/Sydney"
        ):
            raise ValueError("Expected the half-hour Sydney scenario with grid charging and no battery export.")
        self.states = np.arange(minimum, maximum + step_kwh / 2, step_kwh)
        self.initial = int(np.argmin(abs(self.states - initial)))
        if not np.isclose(self.states[self.initial], initial) or not np.isclose(self.states[-1], maximum):
            raise ValueError("Battery charge bounds and initial charge must lie on the charge grid.")
        change = self.states[None, :] - self.states[:, None]
        self.charge = change.clip(min=0) / battery["charge_efficiency"]
        self.discharge = (-change).clip(min=0) * battery["discharge_efficiency"]
        self.allowed = (self.charge <= battery["charge_ac_limit_kw"] * hours) & (
            self.discharge <= battery["discharge_ac_limit_kw"] * hours
        )
        self.default_rate = tariff["default_import_per_kwh"]
        self.peak_rate = tariff["peak_import_per_kwh"]
        self.inventory_rate = self.default_rate / battery["charge_efficiency"]
        self.export_rate = tariff["export_credit_per_kwh"]
        self.peak_weekdays = tariff["peak_weekdays"]
        self.peak_start = time.fromisoformat(tariff["peak_start_inclusive"])
        self.peak_end = time.fromisoformat(tariff["peak_end_exclusive"])

    @cache
    def rates(self, day):
        peak = np.array([
            day.isoweekday() in self.peak_weekdays and self.peak_start <= time(slot // 2, slot % 2 * 30) < self.peak_end
            for slot in range(48)
        ])
        return np.where(peak, self.peak_rate, self.default_rate), peak

    def cost(self, net, rate):
        return np.maximum(net, 0) * rate - np.maximum(-net, 0) * self.export_rate

    def replay(self, forecast_net, actual_net, initial, rates, *, state_history=None):
        """Optimize forecast cost, then replay planned charge targets against actual meters."""
        if state_history is not None:
            state_history.append(self.states[initial])
        count = len(actual_net)
        row = np.arange(count)
        # Penalize deviation from the daily target. Forecasts with too little
        # net demand can make a hard terminal constraint infeasible.
        terminal_penalty = max(self.default_rate, self.peak_rate) * 2
        future = np.broadcast_to(
            abs(self.states - self.states[self.initial]) * terminal_penalty,
            (count, len(self.states)),
        )
        decisions = np.empty((48, count, len(self.states)), dtype=np.intp)
        for slot in reversed(range(48)):
            net = forecast_net[:, slot, None, None]
            feasible = self.allowed & (self.discharge <= np.maximum(net, 0) + 1e-9)
            balance = net + self.charge - self.discharge
            cost = np.where(feasible, self.cost(balance, rates[slot]) + future[:, None, :], np.inf)
            decisions[slot] = cost.argmin(axis=-1)
            future = cost.min(axis=-1)

        planned = initial.copy()
        realized = initial.copy()
        cost = np.zeros(count)
        throughput = np.zeros(count)
        for slot in range(48):
            planned = decisions[slot, row, planned]
            net = actual_net[:, slot]
            feasible = self.allowed[realized] & (self.discharge[realized] <= np.maximum(net, 0)[:, None] + 1e-9)
            # Follow the open-loop target as closely as the current meter permits.
            distance = abs(self.states[None, :] - self.states[planned, None])
            next_state = np.where(feasible, distance, np.inf).argmin(axis=1)
            charge = self.charge[realized, next_state]
            discharge = self.discharge[realized, next_state]
            cost += self.cost(net + charge - discharge, rates[slot])
            throughput += charge + discharge
            realized = next_state
            if state_history is not None:
                state_history.append(self.states[realized])
        return cost, realized, throughput
