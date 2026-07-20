from fastapi import FastAPI

app = FastAPI(title="Wakacje Deals Tracker")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
