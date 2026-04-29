from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def home():
    return {"product": "JetPakt"}


@app.get("/demo")
def demo():
    return {
        "alert": "UNDERSTAFFED",
        "message": "Call in 1–2 staff immediately"
    }
