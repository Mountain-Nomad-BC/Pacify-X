from __future__ import annotations

DEFAULT_NAME = "pump"


class BaseDevice:
    def status(self) -> str:
        return "base"


class Device(BaseDevice):
    kind = "device"

    def __init__(self, name: str = DEFAULT_NAME) -> None:
        self.name = name

    @property
    def label(self) -> str:
        return self.name.upper()

    def status(self) -> str:
        return helper(self.name)


def helper(value: str) -> str:
    return f"ok:{value}"
