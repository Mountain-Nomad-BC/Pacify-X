#!/usr/bin/env python3
"""Verify the repository vault in an installed Obsidian desktop process.

The verifier uses one fresh Obsidian profile, loopback CDP, and an owned process.
It does not install software, access the network, inspect other vaults, or certify
Pacify-X product behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _wait_for_cdp(port: int, deadline: float) -> None:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    last_error = "CDP endpoint did not respond"
    while time.monotonic() < deadline:
        try:
            with urlopen(endpoint, timeout=1) as response:  # noqa: S310 - loopback only
                payload = json.loads(response.read(64 * 1024))
            if payload.get("webSocketDebuggerUrl"):
                return
        except (OSError, ValueError, json.JSONDecodeError) as error:
            last_error = str(error)
        time.sleep(0.25)
    raise TimeoutError(last_error)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _obsidian_is_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq Obsidian.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return '"Obsidian.exe"' in result.stdout


def _open_command(page, name: str, timeout_ms: int) -> None:
    page.keyboard.press("Control+P")
    prompt = page.locator(".prompt-input").last
    prompt.wait_for(state="visible", timeout=timeout_ms)
    prompt.fill(name)
    page.keyboard.press("Enter")


def _graph_canvas(page, graph_type: str, timeout_ms: int):
    selectors = {
        "global": [
            '.workspace-leaf-content[data-type="graph"] canvas',
            '.view-content[data-type="graph"] canvas',
        ],
        "local": [
            '.workspace-leaf-content[data-type="localgraph"] canvas',
            '.workspace-leaf-content[data-type="local-graph"] canvas',
            '.view-content[data-type="localgraph"] canvas',
        ],
    }
    for selector in selectors[graph_type]:
        locator = page.locator(selector).last
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator, selector
        except Exception:  # Playwright timeout types vary by supported version.
            continue
    raise AssertionError(f"visible {graph_type} graph canvas not found")


def _terminate_owned(process: subprocess.Popen, timeout: float = 15) -> bool:
    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        else:
            process.kill()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True


def verify(obsidian: Path, vault: Path, out: Path, timeout: float) -> dict:
    obsidian = obsidian.resolve(strict=True)
    vault = vault.resolve(strict=True)
    out = out.resolve()
    if obsidian.name.casefold() != "obsidian.exe" or not obsidian.is_file():
        raise ValueError("expected an installed Obsidian.exe")
    if not (vault / ".obsidian/graph.json").is_file():
        raise ValueError("vault lacks .obsidian/graph.json")
    if _obsidian_is_running():
        raise RuntimeError(
            "refusing to attach to or disturb a pre-existing Obsidian process"
        )
    out.mkdir(parents=True, exist_ok=False)
    profile = out / "profile"
    profile.mkdir()
    vault_id = hashlib.sha256(str(vault).casefold().encode("utf-8")).hexdigest()[:16]
    (profile / "obsidian.json").write_text(
        json.dumps(
            {
                "updateDisabled": True,
                "vaults": {
                    vault_id: {
                        "path": str(vault),
                        "ts": int(time.time() * 1000),
                        "open": True,
                    }
                }
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    port = _free_loopback_port()
    deadline = time.monotonic() + timeout
    command = [
        str(obsidian),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--disable-background-networking",
        "--disable-component-update",
        "--proxy-server=http://127.0.0.1:9",
        "--proxy-bypass-list=localhost;127.0.0.1",
        "--start-minimized",
    ]
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        env=process_environment,
    )
    receipt = {
        "schema_version": "px.obsidian-native-qa/1",
        "obsidian_executable": str(obsidian),
        "obsidian_sha256": _sha256(obsidian),
        "vault": str(vault),
        "vault_graph_config_sha256": _sha256(vault / ".obsidian/graph.json"),
        "owned_pid": process.pid,
        "loopback_cdp": True,
        "external_network_contained": True,
        "update_disabled": True,
        "external_network_attempt_observed": None,
        "global_graph_verified": False,
        "local_graph_verified": False,
        "exact_note_verified": False,
        "product_certified": False,
        "errors": [],
        "stages": [],
    }

    def stage(name: str, **details) -> None:
        receipt["stages"].append(
            {
                "name": name,
                "elapsed_seconds": round(
                    timeout - max(0.0, deadline - time.monotonic()), 3
                ),
                **details,
            }
        )

    def remaining_ms(cap_seconds: float = 45) -> int:
        return max(1000, int(min(cap_seconds, deadline - time.monotonic()) * 1000))

    current_stage = "wait-for-cdp"
    try:
        _wait_for_cdp(port, deadline)
        stage("cdp-ready", port=port)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            current_stage = "connect-cdp"
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=remaining_ms()
            )
            try:
                pages = [
                    page for context in browser.contexts for page in context.pages
                ]
                if not pages:
                    raise AssertionError("Obsidian exposed no renderer page")
                receipt["renderer_pages"] = [
                    {
                        "title": item.title()[:256],
                        "url_scheme": item.url.split(":", 1)[0],
                    }
                    for item in pages[:16]
                ]
                page = next(
                    (item for item in pages if item.url.startswith("app://obsidian")),
                    pages[-1],
                )
                page.screenshot(
                    path=str(out / "initial-renderer.png"), full_page=True
                )
                current_stage = "wait-for-workspace"
                try:
                    page.locator(".workspace").wait_for(
                        state="visible", timeout=remaining_ms()
                    )
                except Exception:
                    receipt["initial_body_text"] = page.locator("body").inner_text()[
                        :4096
                    ]
                    raise
                receipt["page_title"] = page.title()
                receipt["page_url_scheme"] = page.url.split(":", 1)[0]
                stage("workspace-visible", title=receipt["page_title"][:256])

                current_stage = "open-global-graph"
                _open_command(page, "Open graph view", remaining_ms())
                global_canvas, global_selector = _graph_canvas(
                    page, "global", remaining_ms()
                )
                global_box = global_canvas.bounding_box()
                assert (
                    global_box
                    and global_box["width"] > 0
                    and global_box["height"] > 0
                )
                receipt["global_graph_verified"] = True
                receipt["global_graph_selector"] = global_selector
                page.screenshot(path=str(out / "global-graph.png"), full_page=True)
                stage("global-graph-visible", selector=global_selector)

                current_stage = "open-canonical-note"
                page.keyboard.press("Control+O")
                prompt = page.locator(".prompt-input").last
                prompt.wait_for(state="visible", timeout=remaining_ms())
                prompt.fill("Pacify-X architecture vault")
                page.keyboard.press("Enter")
                title = page.locator(".inline-title").last
                title.wait_for(state="visible", timeout=remaining_ms())
                receipt["opened_note_title"] = title.inner_text().strip()
                receipt["exact_note_verified"] = (
                    receipt["opened_note_title"] == "Pacify-X architecture vault"
                )
                assert receipt["exact_note_verified"]
                stage("canonical-note-visible", title=receipt["opened_note_title"])

                current_stage = "open-local-graph"
                _open_command(page, "Open local graph", remaining_ms())
                local_canvas, local_selector = _graph_canvas(
                    page, "local", remaining_ms()
                )
                local_box = local_canvas.bounding_box()
                assert (
                    local_box
                    and local_box["width"] > 0
                    and local_box["height"] > 0
                )
                receipt["local_graph_verified"] = True
                receipt["local_graph_selector"] = local_selector
                page.screenshot(path=str(out / "local-graph.png"), full_page=True)
                stage("local-graph-visible", selector=local_selector)
            finally:
                try:
                    browser.close()
                except Exception as error:
                    receipt["errors"].append(
                        f"browser-cleanup: {type(error).__name__}: {error}"[:4096]
                    )
    except Exception as error:  # Retain exact bounded failure without false acceptance.
        receipt["passed"] = False
        receipt["errors"].append(
            f"{current_stage}: {type(error).__name__}: {error}"[:4096]
        )
    finally:
        try:
            receipt["owned_process_closed"] = _terminate_owned(process)
        except Exception as error:
            receipt["owned_process_closed"] = False
            receipt["errors"].append(
                f"process-cleanup: {type(error).__name__}: {error}"[:4096]
            )
        log_path = profile / "obsidian.log"
        log_text = ""
        if log_path.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")[:65536]
            receipt["obsidian_log_sha256"] = _sha256(log_path)
        forbidden_network_markers = (
            "Checking for update",
            "Downloading update from http://",
            "Downloading update from https://",
        )
        receipt["external_network_attempt_observed"] = any(
            marker in log_text for marker in forbidden_network_markers
        )
        receipt["update_disabled_observed"] = "Updates disabled." in log_text
        if receipt["external_network_attempt_observed"]:
            receipt["errors"].append(
                "network-containment: Obsidian log contains an external update attempt"
            )
        receipt["passed"] = (
            all(
                receipt[key]
                for key in (
                    "global_graph_verified",
                    "local_graph_verified",
                    "exact_note_verified",
                    "owned_process_closed",
                )
            )
            and not receipt["external_network_attempt_observed"]
            and not receipt["errors"]
        )
        receipt["profile_root"] = str(profile)
        receipt["elapsed_seconds"] = round(
            timeout - max(0.0, deadline - time.monotonic()), 3
        )
        (out / "obsidian_native_qa.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obsidian", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if not 10 <= args.timeout <= 300:
        parser.error("timeout must be between 10 and 300 seconds")
    try:
        receipt = verify(args.obsidian, args.vault, args.out, args.timeout)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(3, f"REFUSED: {error}\n")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("passed") and receipt.get("owned_process_closed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
