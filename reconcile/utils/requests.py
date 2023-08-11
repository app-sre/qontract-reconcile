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

    def __init__(self) -> None:
        self.cache: list[weakref.ref] = []
        self.finalizer: list[weakref.finalize] = []
        self.cache_lock = Lock()

    @staticmethod
    def __default_finalizer(s: requests.Session) -> None:
        s.close()

    def add_session(self, session: requests.Session) -> None:
        with self.cache_lock:
            self.cache.append(weakref.ref(session))

            # This finalizer
            self.finalizer.append(
                weakref.finalize(session, self.__default_finalizer, session)
            )

    def close_all(self) -> None:
        with self.cache_lock:
            for s in self.cache:
                session = s()
                if session:
                    session.close()


global_session_cache = SessionClosingCache()
