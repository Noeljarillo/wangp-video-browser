"""Optional analysis add-on (C2).

Everything heavy (torch, onnxruntime, model weights) is installed into this
folder's own venv (`app/analysis/env`) by the *Install analysis* menu item.
The modules imported by the core (`jobqueue`, `gpu`) are standard-library only;
the worker process runs from the add-on venv.
"""
