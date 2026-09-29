"""Shared Kernel: primitives every bounded context agrees on.

Keep this package tiny and stable. Anything here is a coupling point between
contexts, so only add concepts that truly are universal (identities, base
classes, ports). Context-specific rules belong in contexts/<name>/domain.
"""
