import logging as logger
from contextlib import contextmanager

from django.db import connection


logging = logger.getLogger(__name__)


class AdvisoryLockBusy(RuntimeError):
    pass


@contextmanager
def execute_lock(key1, key2=None, unlock=False, session=False, shared=False, wait=True):
    """
    Creates or destroys an advisory lock within postgres

    :param key1: An int sent to the PG lock function
    :param key2: A 2nd int sent to the PG lock function
    :param unlock: A bool representing whether query should use `unlock`
    :param session: A bool indicating if this should persist outside of transaction
    :param shared: A bool indicating if this should be shared, otherwise exclusive
    :param wait: A bool indicating if it should use a `try` PG function
    """
    if not session:
        if not connection.in_atomic_block:
            raise NotImplementedError("Advisory lock requires transaction")
        if unlock:
            raise NotImplementedError("Transaction level locks unlock automatically")

    keys = [key1]
    if key2 is not None:
        keys.append(key2)

    query = "SELECT pg{_try}_advisory_{xact_}{lock}{_shared}({keys}) AS lock;".format(
        _try="" if wait else "_try",
        xact_="" if session else "xact_",
        lock="unlock" if unlock else "lock",
        _shared="_shared" if shared else "",
        keys=", ".join(["%s" for i in range(0, 2 if key2 is not None else 1)])
    )

    log_query = "'{}' with params {}".format(query, keys)
    logging.debug("Acquiring advisory lock: {}".format(query, log_query))
    with connection.cursor() as c:
        c.execute(query, keys)
        logging.debug("Acquired advisory lock: {}".format(query, log_query))
        yield c


@contextmanager
def advisory_lock(key1, key2=None, shared=False):
    """
    Creates a transaction level advisory lock that blocks until ready

    :param key1: int
    :param key2: int
    :param shared: bool
    """
    with execute_lock(key1, key2=key2, shared=shared) as cursor:
        # this yields the cursor, but the lock will exist until the transaction
        # is either committed or rolled-back
        yield cursor


def try_advisory_lock(key1, key2=None, shared=False):
    """
    Creates a transaction level advisory lock that doesn't block

    :param key1: int
    :param key2: int
    :param shared: bool
    :raises: AdvisoryLockBusy
    """
    with execute_lock(key1, key2=key2, shared=shared, wait=False) as cursor:
        results = cursor.fetchone()
        if not results[0]:
            raise AdvisoryLockBusy("Unable to acquire advisory lock")