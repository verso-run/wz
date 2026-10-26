"""The made-up controller's core: integer smoothing of a moisture probe and a watering valve with hysteresis.

The same code is the "firmware" (sim/device.py runs it as the board would) and the host reference (sim/host_ref.py),
which is what lets the bench check parity byte for byte. Records are 8 bytes: tick (u32), smoothed (i16), valve (i16).
"""
import struct

REC = struct.Struct("<Ihh")
OPEN_BELOW, CLOSE_ABOVE = 380, 420


def run(samples, fault_at=None):
    out, acc, valve = bytearray(), samples[0] * 8 if samples else 0, 0
    for tick, x in enumerate(samples):
        acc += x - (acc >> 3)
        smoothed = acc >> 3
        if fault_at is not None and tick >= fault_at:
            smoothed += 1          # a device-only bug: the parity step must catch it
        if valve == 0 and smoothed < OPEN_BELOW:
            valve = 1
        elif valve == 1 and smoothed > CLOSE_ABOVE:
            valve = 0
        out += REC.pack(tick, smoothed, valve)
    return bytes(out)


def read_inputs(path):
    return [int(line) for line in open(path) if line.strip() and not line.startswith("#")]
