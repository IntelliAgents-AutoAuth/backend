from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "AutoAuth backend running"}