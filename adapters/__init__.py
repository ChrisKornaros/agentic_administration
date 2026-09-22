"""Backend adapters — the tracker edge (design: roadmap/14 §5 layer 2).

`adapters.base` is the interface every backend implements and the error
taxonomy callers catch; `adapters.plane` is the first backend. Nothing
above this package imports a vendor route, header or payload shape.
"""
