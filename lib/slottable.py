import sys

slot_error           = 0x01
slot_reclaim_channel = 0x02

slot_bind_relay      = 0x04
slot_bind_channel    = 0x05
slot_fwd_data        = 0x06

slot_set_cookie      = 0x08

class Slottable(object):
    slots = None

    def __init__(self):
        self.slots = {}

    def register_slot(self, slot_idx, signal_routine):
        if signal_routine:
            self.slots[slot_idx] = signal_routine

    def unregister_slot(self, slot_idx):
        if self.slots.has_key(slot_idx):
            self.slots.pop(slot_idx)

    def unregister_slots(self):
        self.slots.clear()

    def signal_slot(self, slot_idx, attrs):
        if self.slots.has_key(slot_idx):
            self.slots[slot_idx](attrs)


