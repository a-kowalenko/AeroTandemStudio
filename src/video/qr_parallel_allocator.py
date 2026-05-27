import threading
from typing import Optional


class BidirectionalIndexAllocator:
    """Verteilt Indizes bidirektional ohne Duplikate (0-basiert)."""

    def __init__(self, first_index: int, last_index: int):
        self._forward_i = first_index
        self._backward_i = last_index
        self._lock = threading.Lock()

    def next_forward(self) -> Optional[int]:
        with self._lock:
            if self._forward_i > self._backward_i:
                return None
            index = self._forward_i
            self._forward_i += 1
            return index

    def next_backward(self) -> Optional[int]:
        with self._lock:
            if self._backward_i < self._forward_i:
                return None
            index = self._backward_i
            self._backward_i -= 1
            return index
