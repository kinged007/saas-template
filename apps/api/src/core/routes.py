# Frontend route the invitation notification's "Open" button links to. Lives in
# core so the workflow (src/workflows) and the dev seed (src/seed.py) both read
# it without importing each other.
#
# Not the backend API path: see the router prefix in
# src/api/routes/invitations.py, which mounts under /api/v1.

INVITATIONS_ROUTE = "/invitations"
