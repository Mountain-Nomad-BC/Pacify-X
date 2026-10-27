from __future__ import annotations

import unittest


def _make_recovery_doctor(callbacks):
    """Build a recovery doctor with the given callbacks."""
    class Config:
        def __init__(self, callbacks):
            self.event_bus_reconcilers = callbacks.get("event_bus", [])
            self.agent_session_reconcilers = callbacks.get("agent_sessions", [])
            self.resource_reconcilers = callbacks.get("resources", [])

    class Doctor:
        def __init__(self, config):
            self.configuration = config

        def _component(self, name, status, **kwargs):
            return {"name": name, "status": status, **kwargs}

        def check(self, apply=True):
            components = []
            callback_groups = (
                ("event_bus", self.configuration.event_bus_reconcilers),
                ("agent_sessions", self.configuration.agent_session_reconcilers),
            )
            for label, cb_list in callback_groups:
                if not cb_list:
                    components.append(self._component(label, "healthy", configured=False))
                for index, cb in enumerate(cb_list):
                    try:
                        detail = dict(cb(apply))
                        status = "healthy" if detail.get("valid") is True else "blocked"
                        components.append(self._component(f"{label}[{index}]", status, detail=detail))
                    except (OSError, ValueError, RuntimeError) as error:
                        components.append(self._component(f"{label}[{index}]", "blocked", error=error))
            statuses = {str(item["status"]) for item in components}
            status = (
                "blocked" if "blocked" in statuses
                else "degraded" if "degraded" in statuses
                else "healthy"
            )
            return {
                "schema_version": "px.recovery-report/1.0",
                "valid": status == "healthy",
                "status": status,
                "mode": "apply" if apply else "dry_run",
                "forensic_state": "retained",
                "components": components,
            }

    return Doctor(Config(callbacks))


class PXAUD080_RecoveryDoctorFailClosed(unittest.TestCase):
    """PX-AUD-080: recovery doctor must fail-closed on failed/malformed callbacks."""

    def test_callback_missing_valid_reported_blocked(self) -> None:
        def failing_callback(apply):
            return {"status": "failed"}
        doctor = _make_recovery_doctor({"event_bus": [failing_callback]})
        report = doctor.check()
        component = [c for c in report["components"] if c["name"].startswith("event_bus")][0]
        self.assertEqual(component["status"], "blocked")
        self.assertFalse(report["valid"])

    def test_callback_valid_false_string_reported_blocked(self) -> None:
        def failing_callback(apply):
            return {"valid": "false", "status": "failed"}
        doctor = _make_recovery_doctor({"event_bus": [failing_callback]})
        report = doctor.check()
        component = [c for c in report["components"] if c["name"].startswith("event_bus")][0]
        self.assertEqual(component["status"], "blocked")
        self.assertFalse(report["valid"])

    def test_callback_valid_none_reported_blocked(self) -> None:
        def failing_callback(apply):
            return {"valid": None}
        doctor = _make_recovery_doctor({"event_bus": [failing_callback]})
        report = doctor.check()
        component = [c for c in report["components"] if c["name"].startswith("event_bus")][0]
        self.assertEqual(component["status"], "blocked")

    def test_callback_valid_true_reported_healthy(self) -> None:
        def healthy_callback(apply):
            return {"valid": True}
        doctor = _make_recovery_doctor({"event_bus": [healthy_callback]})
        report = doctor.check()
        component = [c for c in report["components"] if c["name"].startswith("event_bus")][0]
        self.assertEqual(component["status"], "healthy")

    def test_callback_exception_reported_blocked(self) -> None:
        def exploding_callback(apply):
            raise RuntimeError("callback exploded")
        doctor = _make_recovery_doctor({"event_bus": [exploding_callback]})
        report = doctor.check()
        component = [c for c in report["components"] if c["name"].startswith("event_bus")][0]
        self.assertEqual(component["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
