from . import checkpoint, dataset, io, visual, utils  # noqa : F401

import warnings as _w
import os.path as _osp

_fw_orig = _w.formatwarning
_w.formatwarning = lambda msg, categ, fname, lineno, line=None: _fw_orig(msg, categ, _osp.split(fname)[1], lineno, '')

__all__ = [name for name in globals() if not name.startswith('_')]
