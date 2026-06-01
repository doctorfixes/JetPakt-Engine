"""JetPakt — Bookkeeping Marketplace API

Post → Bid → Escrow → Execute → Verify → Settle
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes.marketplace import router as marketplace_router

app = FastAPI(
    title="JetPakt Marketplace",
    description="Automated bookkeeping marketplace with arithmetic verification",
    version="0.1.0",
)

# CORS — allow the marketing site to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gojetpakt.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Marketplace API routes
app.include_router(marketplace_router)

# Serve static marketing site
site_dir = os.path.join(os.path.dirname(__file__), "site")
if os.path.isdir(site_dir):
    app.mount("/", StaticFiles(directory=site_dir, html=True), name="site")


@app.get("/api/openapi.json")
async def openapi():
    return app.openapi()
