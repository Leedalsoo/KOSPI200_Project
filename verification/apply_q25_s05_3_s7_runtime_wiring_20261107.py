from pathlib import Path
def rep(path,old,new,first=False):
 p=Path(path); s=p.read_text(encoding="utf-8"); n=s.count(old)
 if n<1 or (not first and n!=1): raise SystemExit(f"MATCH:{path}:{n}:{old[:65]!r}")
 p.write_text(s.replace(old,new,1),encoding="utf-8",newline="")
r="environments/high_speed/virtual_runtime_replay.py"
rep(r,
"        if self.validation_only_s8_risk_profile is not None:\n            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (self.strategy_keys or ())}\n",
"        if self.validation_only_s7_risk_profile is not None:\n            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (self.strategy_keys or ())}\n            if selected_ids != {\"track7_volatility_skew_weekly_insurance\"}:\n                raise ValueError(\"S7_VALIDATION_RUN_MUST_SELECT_ONLY_STRATEGY7\")\n            self.s7_validation_runtime_adapter = S7ValidationOnlyRuntimeAdapter(\n                dataset=self.dataset, manifest_path=self.validation_only_synthetic_manifest,\n                risk_profile_path=self.validation_only_s7_risk_profile,\n            )\n            self.s7_validation_runtime_adapter.bind_run_id(self.run_id)\n        if self.validation_only_s8_risk_profile is not None:\n            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (self.strategy_keys or ())}\n")
rep(r,"            validation_only_s8_runtime_adapter=self.s8_validation_runtime_adapter,\n","            validation_only_s8_runtime_adapter=self.s8_validation_runtime_adapter,\n            validation_only_s7_runtime_adapter=self.s7_validation_runtime_adapter,\n")
c="environments/high_speed/validation_only_trading_calendar.py"
rep(c,"    authoritative: bool = False\n","    authoritative: bool = False\n    strategy7_entry_dates: tuple[date, ...] = ()\n")
rep(c,
"        if any(day.weekday() >= 5 for day in days):\n            raise ValueError(\"VALIDATION_CALENDAR_WEEKEND_DATE_NOT_ALLOWED\")\n        object.__setattr__(self, \"trading_days\", days)\n",
"        if any(day.weekday() >= 5 for day in days):\n            raise ValueError(\"VALIDATION_CALENDAR_WEEKEND_DATE_NOT_ALLOWED\")\n        entry_dates = tuple(self.strategy7_entry_dates)\n        if any(day not in days for day in entry_dates) or len(set(entry_dates)) != len(entry_dates):\n            raise ValueError(\"VALIDATION_CALENDAR_STRATEGY7_ENTRY_DATES_INVALID\")\n        object.__setattr__(self, \"trading_days\", days)\n        object.__setattr__(self, \"strategy7_entry_dates\", entry_dates)\n")
rep(c,
"    def is_new_week_start(self, value: date) -> bool:\n        if not self.is_trading_day(value):\n",
"    @property\n    def validation_only_week_start_dates(self) -> tuple[date, ...] | None:\n        return self.strategy7_entry_dates or None\n\n    def is_new_week_start(self, value: date) -> bool:\n        if not self.is_trading_day(value):\n")
rep(c,
"        try:\n            previous = self.prev_trading_day(value)\n",
"        if self.strategy7_entry_dates:\n            return value in self.strategy7_entry_dates\n        try:\n            previous = self.prev_trading_day(value)\n")
rep(c,
"    return ValidationOnlyTradingCalendar(\n        scenario_id=str(payload.get(\"scenario_id\") or \"\"),\n",
"    policy = payload.get(\"strategy_policy_inputs\") or {}\n    strategy7_dates = tuple(date.fromisoformat(str(value)) for value in (policy.get(\"strategy7_group_entry_dates\") or {}).values())\n    return ValidationOnlyTradingCalendar(\n        scenario_id=str(payload.get(\"scenario_id\") or \"\"),\n")
rep(c,
"        authoritative=bool(schedule.get(\"authoritative\", True)),\n",
"        authoritative=bool(schedule.get(\"authoritative\", True)),\n        strategy7_entry_dates=strategy7_dates,\n")
h="application/composition/market_calendar_hub.py"
rep(h,"        is_new_week = previous.isocalendar().week != observed_date.isocalendar().week\n","        validation_week_starts = getattr(self._calendar, \"validation_only_week_start_dates\", None)\n        is_new_week = (observed_date in validation_week_starts) if validation_week_starts is not None else (previous.isocalendar().week != observed_date.isocalendar().week)\n")
print("PATCHES_APPLIED")
