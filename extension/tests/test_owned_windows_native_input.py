from __future__ import annotations

import importlib.util
import ctypes
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TARGET = Path(__file__).parents[1] / "scripts" / "owned_windows_native_input.py"
SPEC = importlib.util.spec_from_file_location("owned_windows_native_input", TARGET)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class OwnedWindowsNativeInputTests(unittest.TestCase):
    def request(self, **updates):
        now = datetime.now(timezone.utc)
        value = {
            "schema_version": MODULE.SCHEMA_REQUEST,
            "request_id": "12345678-1234-1234-1234-123456789abc",
            "sequence": 7,
            "secret": "a" * 64,
            "vscode_pid": 100,
            "action": "approve",
            "key": "enter",
            "issued_utc": now.isoformat(),
            "expires_utc": (now + timedelta(seconds=5)).isoformat(),
            "correlation": {"request_type": "buildRepositoryGraph", "action_label": "Build graph"},
        }
        value.update(updates)
        return value, now

    def test_process_ancestry_is_bounded_and_exact(self):
        parents = {303: 202, 202: 100, 100: 50, 404: 1}
        self.assertTrue(MODULE.is_owned_process(303, 100, parents))
        self.assertTrue(MODULE.is_owned_process(100, 100, parents))
        self.assertFalse(MODULE.is_owned_process(404, 100, parents))
        self.assertFalse(MODULE.is_owned_process(202, 999, {202: 303, 303: 202}))

    def test_owned_window_selection_is_unique_visible_enabled_and_process_bound(self):
        parents = {303: 202, 202: 100, 100: 50, 304: 100, 404: 1}
        self.assertEqual(MODULE.select_owned_window([(11, 303, True, True), (12, 404, True, True)], 100, parents), (11, 303))
        self.assertIsNone(MODULE.select_owned_window([(11, 303, False, True), (12, 404, True, True)], 100, parents))
        self.assertIsNone(MODULE.select_owned_window([(11, 303, True, True), (13, 304, True, True)], 100, parents))

    def test_activation_attaches_foreground_and_target_queues_once_without_self_attachment(self):
        self.assertEqual(MODULE.activation_thread_ids(10, 20, 30), (20, 30))
        self.assertEqual(MODULE.activation_thread_ids(10, 20, 20), (20,))
        self.assertEqual(MODULE.activation_thread_ids(10, 10, 30), (30,))
        self.assertEqual(MODULE.activation_thread_ids(10, 0, 10), ())

    def test_foreground_recovery_activates_only_the_unique_owned_window_and_rechecks_ancestry(self):
        class Native:
            def __init__(self):
                self.current = (90, 404)
                self.activated = []

            def parents(self):
                return {303: 202, 202: 100, 100: 50, 404: 1}

            def foreground(self):
                return self.current

            def windows(self):
                return [(11, 303, True, True), (90, 404, True, True)]

            def activate(self, hwnd):
                self.activated.append(hwnd)
                self.current = (hwnd, 303)
                return True

        native = Native()
        self.assertEqual(MODULE.resolve_owned_foreground(native, 100), (11, 303, True))
        self.assertEqual(native.activated, [11])
        native.current = (12, 202)
        native.activated.clear()
        self.assertEqual(MODULE.resolve_owned_foreground(native, 100), (12, 202, False))
        self.assertEqual(native.activated, [])

    def test_foreground_recovery_refuses_ambiguous_or_unverified_activation(self):
        class Native:
            def __init__(self, windows, activated_pid=404):
                self._windows = windows
                self.activated_pid = activated_pid
                self.current = (90, 404)

            def parents(self):
                return {303: 100, 304: 100, 404: 1}

            def foreground(self):
                return self.current

            def windows(self):
                return self._windows

            def activate(self, hwnd):
                self.current = (hwnd, self.activated_pid)
                return True

        with self.assertRaisesRegex(PermissionError, "ambiguous"):
            MODULE.resolve_owned_foreground(Native([(11, 303, True, True), (12, 304, True, True)]), 100, 0)
        with self.assertRaisesRegex(PermissionError, "did not become foreground"):
            MODULE.resolve_owned_foreground(Native([(11, 303, True, True)]), 100, 0)

    def test_input_abi_includes_the_full_win32_union(self):
        pointer_64 = ctypes.sizeof(ctypes.c_void_p) == 8
        self.assertEqual(ctypes.sizeof(MODULE._INPUTUNION), 32 if pointer_64 else 24)
        self.assertEqual(ctypes.sizeof(MODULE._INPUT), 40 if pointer_64 else 28)

    @unittest.skipUnless(os.name == "nt", "Win32 bindings require Windows")
    def test_win32_window_ownership_bindings_construct_on_host(self):
        native = MODULE.WindowsInput()
        self.assertTrue(callable(native.foreground))
        self.assertTrue(callable(native.windows))
        self.assertTrue(callable(native.activate))

    def test_request_requires_authentication_sequence_identity_action_and_time(self):
        request, now = self.request()
        config = {"secret": "a" * 64, "vscode_pid": 100}
        self.assertIs(MODULE.validate_request(request, config, 6, now), request)
        focused = dict(request); focused["key"] = "tab-enter"
        self.assertIs(MODULE.validate_request(focused, config, 6, now), focused)
        second = dict(request); second["key"] = "tab-tab-enter"
        self.assertIs(MODULE.validate_request(second, config, 6, now), second)
        for updates, message in [
            ({"secret": "b" * 64}, "authentication"),
            ({"sequence": 6}, "sequence stale"),
            ({"vscode_pid": 101}, "identity mismatch"),
            ({"action": "approve", "key": "escape"}, "action invalid"),
            ({"correlation": {}}, "correlation missing"),
            ({"expires_utc": (now - timedelta(seconds=1)).isoformat()}, "time boundary"),
        ]:
            candidate = dict(request); candidate.update(updates)
            with self.assertRaisesRegex(ValueError, message):
                MODULE.validate_request(candidate, config, 6, now)


if __name__ == "__main__":
    unittest.main()
