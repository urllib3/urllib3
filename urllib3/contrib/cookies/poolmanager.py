#!/usr/bin/python3

__author__ = 'Andrew Wang'

import urllib3.poolmanager

from .opener import RegularOpener, SecureOpener

__all__ = ("PoolManager",)

# Cheap hack to make all the connections automatically handle cookies
# It's easier than overriding!
urllib3.poolmanager.pool_classes_by_scheme = {"http": RegularOpener, "https": SecureOpener}

class PoolManager(urllib3.poolmanager.PoolManager):
    pass