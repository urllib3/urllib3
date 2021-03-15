import collections
import queue


class LifoQueue(queue.LifoQueue):
    def _init(self, _):
        self.queue = collections.deque()
