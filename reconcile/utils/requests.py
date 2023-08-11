import weakref
from threading import Lock

import requests


class SessionClosingCache:
    """
    SessionClosingCache:
        Add session objects to cache
        Cache will hold weakreference to that session object
        The weakreference will also close the session
        Additionally on ending the program, close_all should be called
        Technically it could happen we call close() twice on a session
    """

    def __init__(self):
        self.foo = "bar"
        self.cache: list[weakref] = []
        self.finalizer = []
        self.cache_lock = Lock()

    @staticmethod
    def __default_finalizer(s: requests.Session):
        s.close()

    def add_session(self, session: requests.Session):
        self.cache_lock.acquire(blocking=True)
        self.cache.append(weakref.ref(session))

        # This finalizer
        self.finalizer.append(
            weakref.finalize(session, self.__default_finalizer, session)
        )
        self.cache_lock.release()

    def close_all(self):
        self.cache_lock.acquire(blocking=True)
        for s in self.cache:
            session = s()
            if session:
                session.close()
        self.cache_lock.release()


global_session_cache = SessionClosingCache()
