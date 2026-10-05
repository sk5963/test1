"""Compact mutable key/value adapter for wide measurement rows."""
from array import array
from bisect import bisect_left
from collections.abc import MutableMapping


class NumericValues(MutableMapping):
    def __init__(self, values=()):
        pairs = list(dict(values).items())
        self.keys_ordered = [key for key, _ in pairs]
        self.keys_sorted = sorted(self.keys_ordered)
        positions = {key: index for index, key in enumerate(self.keys_ordered)}
        self.positions = array('I', (positions[key] for key in self.keys_sorted))
        self.numbers = array('d', (value for _, value in pairs))

    def __len__(self):
        return len(self.keys_sorted)

    def __iter__(self):
        return iter(self.keys_ordered)

    def __getitem__(self, key):
        pos = bisect_left(self.keys_sorted, key)
        if pos == len(self) or self.keys_sorted[pos] != key:
            raise KeyError(key)
        return self.numbers[self.positions[pos]]

    def __setitem__(self, key, value):
        pos = bisect_left(self.keys_sorted, key)
        if pos < len(self) and self.keys_sorted[pos] == key:
            self.numbers[self.positions[pos]] = value
        else:
            self.keys_sorted.insert(pos, key)
            self.positions.insert(pos, len(self.keys_ordered))
            self.keys_ordered.append(key)
            self.numbers.append(value)

    def __delitem__(self, key):
        pos = bisect_left(self.keys_sorted, key)
        if pos == len(self) or self.keys_sorted[pos] != key:
            raise KeyError(key)
        index = self.positions[pos]
        del self.keys_sorted[pos]
        del self.positions[pos]
        del self.keys_ordered[index]
        del self.numbers[index]
        self.positions = array('I', (p - (p > index) for p in self.positions))

    def items(self):
        return zip(self.keys_ordered, self.numbers)

    def copy(self):
        return dict(self.items())
