# Debug capture plugin

Standalone, local-only diagnostic capture proof of concept. Python 3.10+, standard library
plus the public bridge SDK. No private application imports, paths, account data or fixtures.

`plugin.py` owns HTTP routes; `store.py` owns the bounded local ring. Browser helper sends only
explicitly selected data after a user action; never collect cookies, storage or DOM automatically.
Keep tests independent of user files and real services. Run only affected Python or Node test files.
Do not start a demo server or browser for visual checks without a user request.
