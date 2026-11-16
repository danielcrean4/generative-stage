"""The world model: projects, kinds from JSON Schema, entities with revisions, typed links and
references to pipeline output. Pure Python with no web framework; the HTTP server and any other
front end call into it. Every dependency (paths, checks) is passed in; nothing here is global.
"""
