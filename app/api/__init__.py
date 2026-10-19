"""Bulk checking of bond numbers against recorded draws, and the optional HTTP API on top of it.

``checker``  pure Python, no extra packages: used by the app itself (Check a list of numbers...)
``schemas``  the Pydantic request / response models of the API
``server``   the FastAPI app (``python main.py --serve``); needs ``pip install fastapi uvicorn``
"""
