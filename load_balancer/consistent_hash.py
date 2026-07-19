import bisect
import math
import random
from dataclasses import dataclass
from typing import Callable


DEFAULT_SLOTS = 512
DEFAULT_VIRTUALS = int(math.log2(DEFAULT_SLOTS))


def default_request_hash(request_id: int) -> int:
    return request_id * 31 + 17


def default_server_hash(server_id: int, virtual_id: int) -> int:
    return server_id * 37 + virtual_id * 13 + 29


@dataclass(frozen=True)
class ServerRecord:
    name: str
    server_id: int


class ConsistentHashMap:
    def __init__(
        self,
        slots: int = DEFAULT_SLOTS,
        virtuals: int = DEFAULT_VIRTUALS,
        request_hash: Callable[[int], int] = default_request_hash,
        server_hash: Callable[[int, int], int] = default_server_hash,
    ):
        self.slots = slots
        self.virtuals = virtuals
        self.request_hash = request_hash
        self.server_hash = server_hash
        self._ring: dict[int, ServerRecord] = {}
        self._sorted_slots: list[int] = []

    def add_server(self, name: str, server_id: int) -> None:
        self.remove_server(name)
        record = ServerRecord(name=name, server_id=server_id)
        # Virtual nodes spread a server's ownership across the ring
        for virtual_id in range(self.virtuals):
            slot = self.server_hash(server_id, virtual_id) % self.slots
            slot = self._probe_free_slot(slot)
            self._ring[slot] = record
            bisect.insort(self._sorted_slots, slot)

    def remove_server(self, name: str) -> None:
        to_remove = [slot for slot, record in self._ring.items() if record.name == name]
        for slot in to_remove:
            del self._ring[slot]
            index = bisect.bisect_left(self._sorted_slots, slot)
            if index < len(self._sorted_slots) and self._sorted_slots[index] == slot:
                self._sorted_slots.pop(index)

    def get_server(self, request_id: int | None = None) -> ServerRecord:
        if not self._sorted_slots:
            raise LookupError("consistent hash ring is empty")

        if request_id is None:
            request_id = random.randint(100000, 999999)

        request_slot = self.request_hash(request_id) % self.slots
        # Pick the first clockwise virtual node, wrapping at the end of the ring
        index = bisect.bisect_left(self._sorted_slots, request_slot)
        if index == len(self._sorted_slots):
            index = 0
        return self._ring[self._sorted_slots[index]]

    def servers(self) -> list[str]:
        names = []
        seen = set()
        for slot in self._sorted_slots:
            name = self._ring[slot].name
            if name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def slot_loads(self) -> dict[str, int]:
        if not self._sorted_slots:
            return {}

        loads: dict[str, int] = {}
        # Each node owns the interval from the preceding node up to its slot
        for index, slot in enumerate(self._sorted_slots):
            previous_slot = self._sorted_slots[index - 1]
            width = (slot - previous_slot) % self.slots or self.slots
            name = self._ring[slot].name
            loads[name] = loads.get(name, 0) + width
        return loads

    def _probe_free_slot(self, start_slot: int) -> int:
        slot = start_slot
        for _ in range(self.slots):
            if slot not in self._ring:
                return slot
            # Resolve a hash collision by scanning forward with wraparound
            slot = (slot + 1) % self.slots
        raise RuntimeError("consistent hash ring has no free slots")
