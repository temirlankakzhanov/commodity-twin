"""Commodity Merchant Digital Twin and Independent Model Validation Lab (MVP).

The package has three layers that depend on each other strictly top to bottom:

* ``mtwin.ui``      - Streamlit presentation (the only layer that imports ``streamlit``).
* ``mtwin.risk`` and ``mtwin.trading`` - pure numerical code, no I/O.
* ``mtwin.data``    - providers, HTTP, caching and fallbacks (the only layer doing I/O).
"""

__version__ = "0.1.0"
