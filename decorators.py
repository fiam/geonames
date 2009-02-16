# -*- coding: utf-8 -*-

# The contents of this file are subject to the Common Public Attribution License 
# Version 1.0 (the "License"); you may not use this file except in compliance with 
# the License. You may obtain a copy of the License at 
# http://www.cpal-dev.com/cpaldemoopen/license. The License is based on the 
# Mozilla Public License Version 1.1 but Sections 14 and 15 have been added to cover 
# use of software over a computer network and provide for limited attribution for 
# the Original Developer. In addition, Exhibit A has been modified to be consistent 
# with Exhibit B.

# Software distributed under the License is distributed on an "AS IS" basis, WITHOUT 
# WARRANTY OF ANY KIND, either express or implied. See the License for the specific 
# anguage governing rights and limitations under the License.

# The Original Code is the byNotes project

# The Initial Developer of the Original Code is Alberto García Hierro
# The Original Developer is Alberto García Hierro

# All portions of the code written by Alberto García Hierro are
# Copyright (C) 2008 Alberto García Hierro
# All Rights Reserved.

from django.core.cache import cache

def cache_set(key, value):
    cache.set(key, value)
    return value

def _cached(func):
    def cached_func(self):
        key = 'cached_property_%s_%s_%s' % \
            (self.__class__.__name__, func.__name__, self.pk)
        val = cache.get(key)
        return cache_set(key, func(self)) if val is None else val

    cached_func.__name__ = func.__name__
    return cached_func

def cached_property(func):
    return property(_cached(func))

def _stored(func):
    key = '_cached_%s' % func.__name__
    def stored_func(self):
        if not hasattr(self, key):
            setattr(self, key, func(self))
        return getattr(self, key)

    stored_func.__name__ = func.__name__
    return stored_func

def stored_property(func):
    return property(_stored(func))

def full_cached_property(func):
    return stored_property(_cached(func))

def cached_method(func):
    def cached_func(self, *args, **kwargs):
        key = 'cached_method_%s_%s_%s_%s_%s' % \
            (self.__class__.__name__, func.__name__, self.pk, hash(args),
            hash(kwargs.iteritems()))
        val = cache.get(key)
        return cache_set(key, func(self, *args, **kwargs)) if val is None else val

    return cached_func
