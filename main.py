from fastapi import FastAPI
from config.dbconfig import engine, Base
import models

app = FastAPI()

Base.metadata.create_all(bind=engine)

@app.get("/")
def home():
    return {"message": "AutoAuth backend running"}