"""Entry point for Vercel's Python runtime (it looks for an `app` object here).

Configuration comes from environment variables set in the Vercel project, e.g. DEMO_MODE=true,
DATABASE_URL=sqlite:////tmp/campus_inbox.db and CORS_ORIGINS=https://<frontend>.vercel.app.
"""

from app.main import create_app

app = create_app()
