from .models import Device, helper


def build_device(name: str) -> Device:
    item = Device(name)
    return item


def describe(name: str) -> str:
    device = build_device(name)
    return helper(device.name)
