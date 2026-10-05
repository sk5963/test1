"""Sequential internal record spool; never reads user-supplied pickle files."""
import pickle
import tempfile


def should_spool(path):
    return path.stat().st_size >= 32 * 1048576


class RowSpool:
    def __init__(self):
        self._file = tempfile.TemporaryFile(mode='w+b')
        self._count = 0

    def append(self, record):
        self._file.seek(0, 2)
        pickle.dump(record, self._file, protocol=pickle.HIGHEST_PROTOCOL)
        self._count += 1

    def __len__(self):
        return self._count

    def __iter__(self):
        self._file.flush()
        self._file.seek(0)
        for _ in range(self._count):
            yield pickle.load(self._file)

    def close(self):
        self._file.close()
