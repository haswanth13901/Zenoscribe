"""Domain-scoped API routers.

routes_api.py was one 638-line module holding fourteen endpoints across
several unrelated domains, so any two changes to the API collided on the
same file. Each module here owns one domain and its own helpers; none of
them import each other.

routes_api.py is now a thin aggregator that includes them in the order
below - which is the order the routes were originally registered in, so
FastAPI's matching behaviour is unchanged.
"""
